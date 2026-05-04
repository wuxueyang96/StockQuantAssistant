import os
import logging

logger = logging.getLogger(__name__)

_ENABLED = None
_CLIENT = None


def _enabled():
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = bool(os.environ.get('OSS_BUCKET'))
    return _ENABLED


def _get_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    import boto3

    kwargs = {
        'service_name': 's3',
        'region_name': os.environ.get('OSS_REGION', 'us-east-1'),
    }

    access_key = os.environ.get('OSS_ACCESS_KEY_ID')
    secret_key = os.environ.get('OSS_ACCESS_KEY_SECRET')
    if access_key and secret_key:
        kwargs['aws_access_key_id'] = access_key
        kwargs['aws_secret_access_key'] = secret_key

    endpoint = os.environ.get('OSS_ENDPOINT')
    if endpoint:
        kwargs['endpoint_url'] = endpoint

    _CLIENT = boto3.client(**kwargs)
    return _CLIENT


def _get_bucket():
    return os.environ['OSS_BUCKET']


def _get_prefix():
    prefix = os.environ.get('OSS_KEY_PREFIX', '').strip('/')
    return prefix + '/' if prefix else ''


def sync_down(data_dir: str):
    if not _enabled():
        logger.info("OSS 未配置 (OSS_BUCKET 为空)，跳过数据下载")
        return

    bucket = _get_bucket()
    prefix = _get_prefix()
    client = _get_client()

    logger.info(f"从 OSS 下载数据: s3://{bucket}/{prefix}*.db -> {data_dir}")

    paginator = client.get_paginator('list_objects_v2')
    count = 0
    try:
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        for page in pages:
            for obj in page.get('Contents', []):
                key = obj['Key']
                if not key.endswith('.db'):
                    continue
                rel_path = key[len(prefix):]
                local_path = os.path.join(data_dir, rel_path)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                client.download_file(bucket, key, local_path)
                count += 1
                logger.info(f"  下载: {rel_path} ({obj['Size']} bytes)")
    except Exception as e:
        logger.error(f"OSS 下载失败: {e}")
        raise

    logger.info(f"OSS 下载完成: {count} 个文件")


def sync_up(data_dir: str):
    if not _enabled():
        logger.info("OSS 未配置，跳过数据上传")
        return

    bucket = _get_bucket()
    prefix = _get_prefix()
    client = _get_client()

    logger.info(f"上传数据到 OSS: {data_dir} -> s3://{bucket}/{prefix}*.db")

    count = 0
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.endswith('.db'):
                continue
            local_path = os.path.join(root, filename)
            rel_path = os.path.relpath(local_path, data_dir)
            remote_key = prefix + rel_path
            client.upload_file(local_path, bucket, remote_key)
            count += 1
            logger.info(f"  上传: {rel_path}")

    logger.info(f"OSS 上传完成: {count} 个文件")
