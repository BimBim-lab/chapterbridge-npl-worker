"""Cloudflare R2 client using boto3 S3-compatible API."""

import os
import boto3
from botocore.config import Config
from typing import Optional
from .utils import get_logger, sha256_hash

logger = get_logger(__name__)

class R2Client:
    """Client for interacting with Cloudflare R2 storage."""
    
    def __init__(self):
        self.endpoint = os.environ.get('R2_ENDPOINT')
        self.access_key = os.environ.get('R2_ACCESS_KEY_ID')
        self.secret_key = os.environ.get('R2_SECRET_ACCESS_KEY')
        self.bucket = os.environ.get('R2_BUCKET', 'chapterbridge-data')
        
        if not all([self.endpoint, self.access_key, self.secret_key]):
            raise ValueError("R2 credentials not fully configured. Check R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'adaptive'}
            )
        )
        logger.info(f"R2 client initialized for bucket: {self.bucket}")
    
    def download(self, key: str) -> bytes:
        """Download a file from R2."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            data = response['Body'].read()
            logger.debug(f"Downloaded {len(data)} bytes from {key}")
            return data
        except Exception as e:
            logger.error(f"Failed to download {key}: {e}")
            raise
    
    def download_text(self, key: str, encoding: str = 'utf-8') -> str:
        """Download a text file from R2."""
        return self.download(key).decode(encoding)
    
    def upload(
        self, 
        key: str, 
        data: bytes, 
        content_type: str = 'application/octet-stream'
    ) -> dict:
        """Upload a file to R2. Returns metadata dict."""
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type
            )
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
    ) -> dict:
        """Upload a text file to R2."""
        return self.upload(key, text.encode(encoding), 'text/plain; charset=utf-8')
    
    def exists(self, key: str) -> bool:
        """Check if a key exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
    def delete(self, key: str) -> bool:
        """Delete a file from R2."""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
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
