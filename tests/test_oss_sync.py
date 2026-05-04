import logging
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.oss_sync import sync_down, sync_up


def _reset_oss_module():
    import app.services.oss_sync as m
    m._ENABLED = None
    m._CLIENT = None


@pytest.fixture(autouse=True)
def clean_oss_env(caplog):
    for key in ('OSS_BUCKET', 'OSS_ENDPOINT', 'OSS_REGION',
                'OSS_ACCESS_KEY_ID', 'OSS_ACCESS_KEY_SECRET', 'OSS_KEY_PREFIX'):
        os.environ.pop(key, None)
    _reset_oss_module()
    caplog.set_level(logging.INFO)
    yield
    _reset_oss_module()


class TestOSSyncDisabled:
    def test_sync_down_noop_when_not_configured(self, tmp_path, caplog):
        sync_down(str(tmp_path))
        assert 'OSS 未配置' in caplog.text

    def test_sync_up_noop_when_not_configured(self, tmp_path, caplog):
        sync_up(str(tmp_path))
        assert 'OSS 未配置' in caplog.text


class TestOSSyncWithMock:
    @pytest.fixture
    def oss_env(self):
        os.environ['OSS_BUCKET'] = 'test-bucket'
        os.environ['OSS_REGION'] = 'us-east-1'
        _reset_oss_module()
        yield
        os.environ.pop('OSS_BUCKET', None)
        os.environ.pop('OSS_REGION', None)
        _reset_oss_module()

    @pytest.mark.usefixtures('oss_env')
    def test_sync_down_downloads_db_files(self, tmp_path):
        mock_client = mock.MagicMock()
        mock_paginator = mock.MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {'Contents': [
                {'Key': 'metadata.db', 'Size': 4096},
                {'Key': 'a_stock.db', 'Size': 8192},
                {'Key': 'hk_stock.db', 'Size': 16384},
                {'Key': 'notes.txt', 'Size': 100},
            ]}
        ]

        with mock.patch('boto3.client', return_value=mock_client):
            sync_down(str(tmp_path))

        assert mock_client.download_file.call_count == 3
        downloaded = {call[0][1] for call in mock_client.download_file.call_args_list}
        assert downloaded == {'metadata.db', 'a_stock.db', 'hk_stock.db'}

    @pytest.mark.usefixtures('oss_env')
    def test_sync_down_empty_bucket(self, tmp_path, caplog):
        mock_client = mock.MagicMock()
        mock_paginator = mock.MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{}]

        with mock.patch('boto3.client', return_value=mock_client):
            sync_down(str(tmp_path))

        mock_client.download_file.assert_not_called()
        assert '下载完成: 0' in caplog.text

    @pytest.mark.usefixtures('oss_env')
    def test_sync_up_uploads_all_db_files(self, tmp_path):
        (tmp_path / 'metadata.db').write_text('metadata')
        (tmp_path / 'a_stock.db').write_text('a_stock')
        (tmp_path / 'us_stock.db').write_text('us_stock')
        (tmp_path / 'readme.txt').write_text('readme')

        mock_client = mock.MagicMock()

        with mock.patch('boto3.client', return_value=mock_client):
            sync_up(str(tmp_path))

        assert mock_client.upload_file.call_count == 3
        uploaded = {call[0][0] for call in mock_client.upload_file.call_args_list}
        assert uploaded == {str(tmp_path / 'metadata.db'),
                            str(tmp_path / 'a_stock.db'),
                            str(tmp_path / 'us_stock.db')}

    @pytest.mark.usefixtures('oss_env')
    def test_sync_down_with_key_prefix(self, tmp_path):
        os.environ['OSS_KEY_PREFIX'] = 'prod/2024/'
        _reset_oss_module()

        mock_client = mock.MagicMock()
        mock_paginator = mock.MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {'Contents': [
                {'Key': 'prod/2024/metadata.db', 'Size': 4096},
                {'Key': 'prod/2024/a_stock.db', 'Size': 8192},
            ]}
        ]

        with mock.patch('boto3.client', return_value=mock_client):
            sync_down(str(tmp_path))

        assert mock_client.download_file.call_count == 2
        for call in mock_client.download_file.call_args_list:
            _, key, _ = call[0]
            assert key.startswith('prod/2024/')

    @pytest.mark.usefixtures('oss_env')
    def test_sync_up_with_key_prefix(self, tmp_path):
        os.environ['OSS_KEY_PREFIX'] = 'prod/2024/'
        _reset_oss_module()

        (tmp_path / 'metadata.db').write_text('data')

        mock_client = mock.MagicMock()

        with mock.patch('boto3.client', return_value=mock_client):
            sync_up(str(tmp_path))

        mock_client.upload_file.assert_called_once()
        _, bucket, remote_key = mock_client.upload_file.call_args[0]
        assert remote_key == 'prod/2024/metadata.db'

    @pytest.mark.usefixtures('oss_env')
    def test_sync_with_custom_endpoint(self, tmp_path):
        os.environ['OSS_ENDPOINT'] = 'https://oss-cn-hangzhou.aliyuncs.com'
        os.environ['OSS_ACCESS_KEY_ID'] = 'ak-test'
        os.environ['OSS_ACCESS_KEY_SECRET'] = 'sk-test'
        _reset_oss_module()

        mock_client = mock.MagicMock()
        mock_paginator = mock.MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{}]

        with mock.patch('boto3.client') as mock_boto3_client:
            mock_boto3_client.return_value = mock_client
            sync_down(str(tmp_path))

        call_kwargs = mock_boto3_client.call_args[1]
        assert call_kwargs['endpoint_url'] == 'https://oss-cn-hangzhou.aliyuncs.com'
        assert call_kwargs['aws_access_key_id'] == 'ak-test'
        assert call_kwargs['aws_secret_access_key'] == 'sk-test'

    @pytest.mark.usefixtures('oss_env')
    def test_sync_up_nested_dir(self, tmp_path):
        subdir = tmp_path / 'sub'
        subdir.mkdir()
        (subdir / 'data.db').write_text('nested')
        (tmp_path / 'top.db').write_text('top')

        mock_client = mock.MagicMock()

        with mock.patch('boto3.client', return_value=mock_client):
            sync_up(str(tmp_path))

        assert mock_client.upload_file.call_count == 2
        uploaded = {call[0][0] for call in mock_client.upload_file.call_args_list}
        assert uploaded == {str(tmp_path / 'top.db'), str(subdir / 'data.db')}

    @pytest.mark.usefixtures('oss_env')
    def test_sync_down_error_raises(self, tmp_path):
        mock_client = mock.MagicMock()
        mock_client.get_paginator.side_effect = RuntimeError('s3 unavailable')

        with mock.patch('boto3.client', return_value=mock_client):
            with pytest.raises(RuntimeError, match='s3 unavailable'):
                sync_down(str(tmp_path))


@pytest.mark.skipif(
    not __import__('importlib.util').util.find_spec('moto'),
    reason='moto not installed, run: pip install moto[s3]'
)
class TestOSSyncWithMoto:
    @pytest.fixture(autouse=True)
    def setup_moto(self):
        import boto3
        from moto import mock_aws
        self.mock = mock_aws()
        self.mock.start()

        os.environ['OSS_BUCKET'] = 'test-bucket'
        os.environ['OSS_REGION'] = 'us-east-1'
        _reset_oss_module()

        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-bucket')

        yield

        self.mock.stop()
        os.environ.pop('OSS_BUCKET', None)
        os.environ.pop('OSS_REGION', None)
        _reset_oss_module()

    def test_roundtrip_upload_then_download(self, tmp_path):
        src_dir = tmp_path / 'src'
        dst_dir = tmp_path / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        (src_dir / 'metadata.db').write_text('{"version": 1}')
        (src_dir / 'a_stock.db').write_text('stock data')

        sync_up(str(src_dir))
        sync_down(str(dst_dir))

        assert (dst_dir / 'metadata.db').read_text() == '{"version": 1}'
        assert (dst_dir / 'a_stock.db').read_text() == 'stock data'

    def test_roundtrip_with_prefix(self, tmp_path):
        os.environ['OSS_KEY_PREFIX'] = 'tenant/alpha'
        _reset_oss_module()

        src_dir = tmp_path / 'src'
        dst_dir = tmp_path / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        (src_dir / 'metadata.db').write_text('prefixed data')

        sync_up(str(src_dir))
        sync_down(str(dst_dir))

        assert (dst_dir / 'metadata.db').read_text() == 'prefixed data'

    def test_sync_down_empty_bucket_no_error(self, tmp_path, caplog):
        sync_down(str(tmp_path))
        assert '下载完成: 0' in caplog.text

    def test_sync_up_no_db_files(self, tmp_path, caplog):
        (tmp_path / 'notes.txt').write_text('hello')
        sync_up(str(tmp_path))
        assert '上传完成: 0' in caplog.text

    def test_large_file_roundtrip(self, tmp_path):
        src_dir = tmp_path / 'src'
        dst_dir = tmp_path / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        content = os.urandom(1024 * 256)
        (src_dir / 'large.db').write_bytes(content)

        sync_up(str(src_dir))
        sync_down(str(dst_dir))

        assert (dst_dir / 'large.db').read_bytes() == content

    def test_sync_down_overwrites_existing(self, tmp_path):
        src_dir = tmp_path / 'src'
        dst_dir = tmp_path / 'dst'
        src_dir.mkdir()
        dst_dir.mkdir()

        # pre-create a stale file in dst
        (dst_dir / 'metadata.db').write_text('stale')

        (src_dir / 'metadata.db').write_text('fresh')

        sync_up(str(src_dir))
        sync_down(str(dst_dir))

        assert (dst_dir / 'metadata.db').read_text() == 'fresh'
