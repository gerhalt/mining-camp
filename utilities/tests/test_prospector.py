import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from unittest import TestCase
from shutil import rmtree
from zipfile import ZipFile

import boto3
import sure
from freezegun import freeze_time
from moto import mock_s3

from utilities.prospector import Prospector


S3_DATE_FMT = '%Y%m%dT%H%M%S'


class TestProspector(TestCase):

    def setUp(self):
        # mock S3 is used for all tests
        self.mock = mock_s3()
        self.mock.start()

        # create a connection to our mock S3 and populate it
        self.s3_client = boto3.client('s3', region_name='us-east-1')
        self.s3_client.create_bucket(Bucket='my_bucket')

        # make a temporary directory to work in, so it can be cleaned up later
        self.temp_dir = tempfile.mkdtemp()

        self.cfg = {
            'server_name': 'my_server',
            'world_name': 'my_world',
            'server_root_dir': self.temp_dir,
            's3_bucket': 'my_bucket'
        }

        # create mock server and world directories
        self.server_path = os.path.join(self.temp_dir, self.cfg['server_name'])
        self.world_path = os.path.join(self.server_path, self.cfg['world_name'])
        os.makedirs(self.world_path)

        self.populate_mock_server()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        self.mock.stop()

    def populate_mock_server(self):
        """
        Populates a mock server directory with files, including a nested
        structure in the world subdirectory.
        """
        # write a number of files to the server directory
        for i in range(0, 4):
            with open(os.path.join(self.server_path, str(i)), 'w') as f:
                f.write(os.urandom(33))

        # and to the world directory, nested in subfolders
        for f in range(0, 3):
            folder_path = os.path.join(self.world_path, 'folder-' + str(f))
            os.mkdir(folder_path)

            for i in range(0, 7):
                with open(os.path.join(folder_path, str(i)), 'w') as f:
                    f.write(os.urandom(100))

    def checksum_walk(self, path):
        """
        Given a `path`, returns a dictionary of `relative_path` => MD5
        `checksum` pairs. `relative_path` is created by stripping `path` off
        all absolute paths.
        """
        # traverse the original world directory, gathering paths and checksums
        checksums = {}
        for folder, _, files in os.walk(path):
            relative_folder = folder.replace(path, '')
            for file_name in files:
                file_path = os.path.join(folder, file_name)
                relative_path = os.path.join(relative_folder, file_name)
                with open(file_path, 'r') as f:
                    checksums[relative_path] = hashlib.md5(f.read()).hexdigest()
        return checksums

    def test_properties(self):
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # it should be able to give us the s3 prefix and the local backup directory
        p.s3_backup_prefix.should.equal('my_server/backups/my_world')
        p.server_path.should.equal(os.path.join(self.temp_dir, 'my_server'))
        p.world_path.should.equal(os.path.join(self.temp_dir, 'my_server', 'my_world'))

    def test_backup_creation(self):
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # and a temporary directory to extract archives to
        extraction_dir = os.path.join(self.temp_dir, 'extraction')
        os.mkdir(extraction_dir)

        backup_path = p.create_current_backup()
        backup_dir = os.path.dirname(backup_path)

        try:
            with ZipFile(backup_path, 'r') as z:
                members_info = z.infolist()

                # the number of files created should match the count in the
                # archive
                len(members_info).should.equal(21)

                # all filenames should start with the world name, indicating
                # only world-related files were packed
                for zinfo in members_info:
                    zinfo.filename.startswith(self.cfg['world_name']).should.be.true

                z.extractall(extraction_dir)

            # compare the paths and checksums of the original world directory
            # with the one just extracted
            extracted_world_path = os.path.join(extraction_dir, self.cfg['world_name'])
            extracted_checksums = self.checksum_walk(extracted_world_path)
            original_checksums = self.checksum_walk(p.world_path)

            extracted_checksums.should.equal(original_checksums)
        finally:
            rmtree(os.path.dirname(backup_path))

    def test_s3_backup_key(self):
        # Given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # generate a backup key from a certain datetime
        dt = datetime(2020, 3, 4, 12, 35, 40)
        key = p.s3_backup_key(dt)

        # it should be formatted as expected
        key.should.equal('my_server/backups/my_world-20200304T123540.zip')

        # and, when converted backwards to a datetime
        key_dt = p.backup_time_from_key(key)
        
        # it should equal the original datetime
        key_dt.should.equal(dt)

    @freeze_time("2020-03-04 02:34:56")
    def test_push_current_backup(self): 
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # there should initially be no backups present in S3
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(0)

        # but when we push a current backup
        p.push_current_backup() 

        # there now should be a backup present in S3
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(1)

        # and the timestamp should be current
        backup_meta = response['Contents'][0]
        backup_time = p.backup_time_from_key(backup_meta['Key'])
        backup_time.should.equal(datetime(2020, 3, 4, 2, 34, 56))

    def test_upload_backup(self):
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # create a dummy backup archive
        mock_archive = os.path.join(self.temp_dir, 'backup.zip')
        with open(mock_archive, 'w') as f:
            f.write(os.urandom(100))

        # upload some backups
        time = datetime(2020, 5, 23, 11, 45)
        backup_times = []
        for i in range(0, 5):
            backup_times.append(time)
            
            with freeze_time(time):
                p.upload_backup(mock_archive)
            
            # shift the clock ahead for the next backup
            time += timedelta(hours=13)

        # now, looking in S3, all backups should be present
        response = self.s3_client.list_objects_v2(Bucket=self.cfg['s3_bucket'])
        response['KeyCount'].should.equal(len(backup_times))

        # and the tags for each backup should be correct, with the newest
        # backup tagged as `new`, and the rest tagged as `old`, intended for
        # use by the lifecycle rules in place on the bucket.
        for item in response['Contents']:
            response = self.s3_client.get_object_tagging(
                Bucket=self.cfg['s3_bucket'],
                Key=item['Key']
            )

            # convert the tags into an easier-to-use dictionary format
            tags = {t['Key']: t['Value'] for t in response['TagSet']}

            # check them against the backup times
            bt = p.backup_time_from_key(item['Key']) 
            if bt in backup_times[:-1]:
                tags.should.equal({'backup': 'old'})
            elif bt == backup_times[-1]:
                tags.should.equal({'backup': 'new'})
            else:
                raise Exception('Unexpected backup key \'{}\''.format(item['Key']))

    def test_get_most_recent_backup_key(self):
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # create a dummy backup archive
        mock_archive = os.path.join(self.temp_dir, 'backup.zip')
        with open(mock_archive, 'w') as f:
            f.write(os.urandom(100))

        # upload a few backups
        time = datetime(2020, 5, 23, 11, 45)
        backup_times = []
        for i in range(0, 5):
            backup_times.append(time)
            
            with freeze_time(time):
                p.upload_backup(mock_archive)
            
            # shift the clock ahead for the next backup
            time += timedelta(hours=13)

        # if the most recent one is requested, the date should be that of
        # the last backup made
        backup_key = p.get_most_recent_backup_key()
        backup_key.should.equal('my_server/backups/my_world-20200525T154500.zip')

    def test_fetch_most_recent_backup(self):
        # given a Prospector created with the base config
        p = Prospector(**self.cfg)

        # create and upload some backups, with different world contents
        time = datetime(2020, 5, 23, 11, 45)
        backup_times = []
        for i in range(0, 5):
            backup_times.append(time)

            # destroy and recreate so the contents vary
            shutil.rmtree(self.server_path)
            os.makedirs(self.world_path)

            self.populate_mock_server()
            
            with freeze_time(time):
                p.push_current_backup()

            time += timedelta(days=27)

        # get the checksum of the current world, then blow it awayd
        current_world_checksum = self.checksum_walk(self.world_path)
        shutil.rmtree(self.world_path)

        # fetch the latest backup from S3
        p.fetch_most_recent_backup()
        backup_world_checksum = self.checksum_walk(self.world_path)

        # all checksums should match
        len(current_world_checksum).should.equal(21)
        current_world_checksum.should.equal(backup_world_checksum)
