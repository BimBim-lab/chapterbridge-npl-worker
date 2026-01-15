"""Cloudflare R2 client using boto3 S3-compatible API with robust retry handling."""

import os
import time
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectionError, EndpointConnectionError
from typing import Optional, Dict, Any
from .utils import get_logger, sha256_hash

logger = get_logger(__name__)

R2_MAX_RETRIES = int(os.environ.get('R2_MAX_RETRIES', '3'))
R2_RETRY_DELAY = float(os.environ.get('R2_RETRY_DELAY', '1.0'))


class R2Client:
    """Client for interacting with Cloudflare R2 storage with retry logic."""
    
    def __init__(self):
        self.endpoint = os.environ.get('R2_ENDPOINT')
        self.access_key = os.environ.get('R2_ACCESS_KEY_ID')
        self.secret_key = os.environ.get('R2_SECRET_ACCESS_KEY')
        self.bucket = os.environ.get('R2_BUCKET', 'chapterbridge-data')
        self.max_retries = R2_MAX_RETRIES
        self.retry_delay = R2_RETRY_DELAY
        
        if not all([self.endpoint, self.access_key, self.secret_key]):
            raise ValueError("R2 credentials not fully configured. Check R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        
        # Fix SSL handshake issues with Cloudflare R2
        import ssl
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            verify=False,  # Disable SSL verification (RunPod SSL issues with R2)
            config=Config(
                signature_version='s3v4',
                retries={'max_attempts': self.max_retries, 'mode': 'adaptive'},
                connect_timeout=30,
                read_timeout=60
            )
        )
        logger.info(f"R2 client initialized for bucket: {self.bucket} (max_retries: {self.max_retries})")
    
    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if operation should be retried."""
        if attempt >= self.max_retries:
            return False
        
        if isinstance(error, (ConnectionError, EndpointConnectionError)):
            return True
        
        if isinstance(error, ClientError):
            error_code = error.response.get('Error', {}).get('Code', '')
            if error_code in ('InternalError', 'ServiceUnavailable', 'SlowDown', 'RequestTimeout'):
                return True
        
        return False
    
    def _retry_operation(self, operation, *args, **kwargs) -> Any:
        """Execute an operation with retry logic."""
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                
                if self._should_retry(e, attempt):
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"R2 operation failed (attempt {attempt + 1}): {e}. Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    raise
        
        raise last_error
    
    def download(self, key: str, fail_if_missing: bool = True) -> Optional[bytes]:
        """
        Download a file from R2.
        
        Args:
            key: The R2 key to download
            fail_if_missing: If True, raises error when key doesn't exist. If False, returns None.
        
        Returns:
            File contents as bytes, or None if not found and fail_if_missing=False
        """
        def _download():
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            data = response['Body'].read()
            logger.debug(f"Downloaded {len(data)} bytes from {key}")
            return data
        
        try:
            return self._retry_operation(_download)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchKey' or error_code == '404':
                if fail_if_missing:
                    logger.error(f"Required file not found in R2: {key}")
                    raise FileNotFoundError(f"R2 key not found: {key}")
                else:
                    logger.debug(f"File not found (optional): {key}")
                    return None
            raise
        except Exception as e:
            logger.error(f"Failed to download {key}: {e}")
            raise
    
    def download_text(self, key: str, encoding: str = 'utf-8', fail_if_missing: bool = True) -> Optional[str]:
        """Download a text file from R2."""
        data = self.download(key, fail_if_missing=fail_if_missing)
        if data is None:
            return None
        return data.decode(encoding)
    
    def upload(
        self, 
        key: str, 
        data: bytes, 
        content_type: str = 'application/octet-stream'
    ) -> Dict[str, Any]:
        """Upload a file to R2 with retry logic. Returns metadata dict."""
        def _upload():
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type
            )
        
        try:
            self._retry_operation(_upload)
            file_hash = sha256_hash(data)
            logger.info(f"Uploaded {len(data)} bytes to {key}")
            return {
                'key': key,
                'bytes': len(data),
                'sha256': file_hash,
                'content_type': content_type
            }
        except Exception as e:
            logger.error(f"Failed to upload {key}: {e}")
            raise
    
    def upload_text(
        self, 
        key: str, 
        text: str, 
        encoding: str = 'utf-8'
    ) -> Dict[str, Any]:
        """Upload a text file to R2."""
        return self.upload(key, text.encode(encoding), 'text/plain; charset=utf-8')
    
    def exists(self, key: str) -> bool:
        """Check if a key exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404' or error_code == 'NoSuchKey':
                return False
            raise
    
    def delete(self, key: str) -> bool:
        """Delete a file from R2."""
        def _delete():
            self.client.delete_object(Bucket=self.bucket, Key=key)
        
        try:
            self._retry_operation(_delete)
            logger.info(f"Deleted {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete {key}: {e}")
            raise


_r2_client: Optional[R2Client] = None

def get_r2_client() -> R2Client:
    """Get singleton R2 client instance."""
    global _r2_client
    if _r2_client is None:
        _r2_client = R2Client()
    return _r2_client
