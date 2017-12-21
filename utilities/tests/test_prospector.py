import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from unittest import TestCase

import boto3
import sure
from moto import mock_s3

from utilities.prospector import Prospector


AROMA_FMT = 'dangerworld-backup-%Y-%m-%d--%H-%M.zip'
FTB_UTILS_FMT = '%Y-%m-%d-%H-%M-%S.zip'
S3_DATE_FMT = '%Y%m%dT%H%M%S'


class TestProspector(TestCase):

    def setUp(self):
      # Mock S3 is used for all tests
        self.mock = mock_s3()
        self.mock.start()

        # Create a connection to our mock S3 and populate it
        self.s3_client = boto3.client('s3', region_name='us-east-1')
        self.s3_client.create_bucket(Bucket='my_bucket')

        # Make a temporary directory to simulate the server root
        self.temp_dir = tempfile.mkdtemp()

        self.cfg = {
            'server_name': 'my_server',
            'world_name': 'my_world',
            'server_root_dir': self.temp_dir,
            's3_bucket': 'my_bucket'
        }

        # Create the empty backup directory
        self.backup_path = os.path.join(self.temp_dir, 'my_server', 'backups')
        os.makedirs(self.backup_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        self.mock.stop()

    def test_properties(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # It should be able to give us the s3 prefix and the local backup directory
        p.s3_backup_prefix.should.equal('my_server/backups/my_world')
        p.local_backup_path.should.equal(self.backup_path)

    def test_push_most_recent_backup_no_backups(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # and no generated backups
        # when attempting to push the most recent backup
        p.push_most_recent_backup()

        # There should be nothing in S3 still, because no backup was available
        # to push
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(0)

    def test_push_most_recent_aroma_backup(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # and three Aroma backups:
        # backups/          OLD
        old_backup = (datetime.now() - timedelta(minutes=30)).strftime(AROMA_FMT)
        with open(os.path.join(self.backup_path, old_backup), 'w') as f:
            f.write('')

        # backups/my_world/     NEW
        # this should be the backup used; mark the backup time string and
        # convert it back to a datetime (because Aroma strips off the seconds)
        backup_time = datetime.now() - timedelta(minutes=15)
        new_backup = backup_time.strftime(AROMA_FMT)
        backup_time = datetime.strptime(new_backup, AROMA_FMT)

        world_backup_path = os.path.join(self.backup_path, self.cfg['world_name'])
        os.makedirs(world_backup_path)
        with open(os.path.join(world_backup_path, new_backup), 'w') as f:
            f.write('')

        # backups/not_my_world/ NEWEST
        # this backup should be ignored, because it's in a backup subdirectory
        # that isn't the configured world, even though it's the newest backup
        newest_backup = datetime.now().strftime(AROMA_FMT)
        other_backup_path = os.path.join(self.backup_path, 'my_other_world')
        os.makedirs(other_backup_path)
        with open(os.path.join(other_backup_path, newest_backup), 'w') as f:
            f.write('')

        # when pushing the most recent backup
        p.push_most_recent_backup()

        # it should be available in S3
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(1)

        s3_key = 'my_server/backups/my_world-{}.zip'.format(backup_time.strftime(S3_DATE_FMT))
        response['Contents'][0]['Key'].should.equal(s3_key)

    def test_push_most_recent_backup_ftbutils_backup(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # and two FTB backups
        old_backup = (datetime.now() - timedelta(minutes=30)).strftime(FTB_UTILS_FMT)
        with open(os.path.join(self.backup_path, old_backup), 'w') as f:
            f.write('')

        backup_time = datetime.now()
        new_backup = backup_time.strftime(FTB_UTILS_FMT)
        with open(os.path.join(self.backup_path, new_backup), 'w') as f:
            f.write('')

        # when pushing the most recent backup
        p.push_most_recent_backup()

        # it should be available in S3
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(1)

        s3_key = 'my_server/backups/my_world-{}.zip'.format(backup_time.strftime(S3_DATE_FMT))
        response['Contents'][0]['Key'].should.equal(s3_key)

    def test_push_most_recent_backup_already_pushed(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # and a backup
        backup_time = datetime.now()
        new_backup = backup_time.strftime(FTB_UTILS_FMT)
        with open(os.path.join(self.backup_path, new_backup), 'w') as f:
            f.write('')

        # when pushing the most recent backup
        p.push_most_recent_backup()

        # it should be available in S3
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])

        # when we attempt to push a backup again
        p.push_most_recent_backup()

        # and compare the s3 responses, there should still be a single s3 item
        # with an identical last modified timestamp
        response2 = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(response2['KeyCount'])
        response['Contents'][0]['LastModified'].should.equal(response2['Contents'][0]['LastModified'])
