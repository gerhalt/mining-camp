#!/usr/bin/env python
"""
Deals with S3 interactions, including pulling the server, pushing backups,
tagging old backups to expire, and more.
"""

import os
import re
import zipfile
from argparse import ArgumentParser
from datetime import datetime, timedelta

import boto3

# Functionality
# 1. Restore from most recent backup
# 2. Back up current state (for example on shutdown)0
# 3. Back up archived backup

# Get current S3 inventory
# Determine the last backup stored in S3
# Look at new backups since that timestamp by iterating over
#     /minecraft/<world>/backups/<year>/<month>/<day>/<file>.zip
#
# Always keep the most recent backup

AROMA_BACKUP_RE = re.compile('\w+-\w+-([\d-]+).zip')
AROMA_BACKUP_DATE_FMT = '%Y-%m-%d--%H-%M'

S3_BACKUP_RE = re.compile('\w+-(\d{8}T\d{6}).zip')
S3_BACKUP_DATE_FMT = '%Y%m%dT%H%M%S'

class Prospector(object):
    """
    Deals with world backup, archival and retrieval from S3.
    """

    def __init__(self, s3_bucket, server_name, world_name, server_root_dir):
        self.server_name = server_name
        self.world_name = world_name
        self.server_root_dir = server_root_dir

        self.s3_bucket = s3_bucket
        self.client = boto3.client('s3')


    def fetch_most_recent_backup(self):
        """
        Fetches the most recent backup in S3 and returns the local temporary
        file path.
        """
        key = self.get_most_recent_backup_key()

        # If a key isn't returned, there's nothing to do
        if key:
            print "Downloading backup from S3: {}".format(key)

            tmp_path = os.path.join('/tmp', os.path.basename(key))
            self.client.download_file(self.s3_bucket,
                                      key,
                                      tmp_path)

            with zipfile.ZipFile(tmp_path, 'r') as z:
                # This makes the assumption that the archive contains the world
                # as a subfolder, so it extracts correctly.
                z.extractall(self.server_root_dir)

                # TODO: Handle zipfile.BadZipFile error

            # Cleanup
            os.remove(tmp_path)
        else:
            print "No backups found!"


    def push_most_recent_backup(self):
        """
        Checks for the most recent backup in the server's backup directory and
        pushes it to S3 if it hasn't already been uploaded.
        """

        latest_path = None
        latest_stamp = None
        for root, dirs, files in os.walk(self._backup_path):
            # Check each file to determine whether it matches our Aroma backup
            # naming convention.
            for f in files:
                result = AROMA_BACKUP_RE.match(f)
                if result:
                    backup_time = datetime.strptime(result.group(1),
                                                    AROMA_BACKUP_DATE_FMT)
                    if not latest_stamp or latest_stamp < backup_time:
                        latest_stamp = backup_time
                        latest_path = os.path.join(root, f)

        # At this point we've found the latest local backup, which we should
        # compare against the latest S3 backup to see whether it has already
        # been uploaded.
        latest_s3 = self.get_most_recent_backup_key()
        latest_s3_stamp = None
        if latest_s3:
            result = S3_BACKUP_RE.match(os.path.basename(latest_s3))
            latest_s3_stamp = datetime.strptime(result.group(1),
                                                S3_BACKUP_DATE_FMT)

        if not latest_s3_stamp or latest_stamp > latest_s3_stamp:
            print "Uploading file to S3: {}".format(latest_path)
            self.client.upload_file(latest_path,
                                    self.s3_bucket,
                                    self._s3_backup_key(latest_stamp))

            # Tag this upload with 'backup': 'current' and the previous with
            # 'backup': 'old' so we can work lifecycle magic on previous
            # backups.
            self.client.put_object_tagging(
                Bucket='josh-minecraft',
                Key=self._s3_backup_key(latest_stamp),
                Tagging={
                    'TagSet': [
                        {
                            'Key': 'backup',
                            'Value': 'current'
                        }
                    ]
                }
            )

            self.client.put_object_tagging(
                Bucket='josh-minecraft',
                Key=self._s3_backup_key(latest_stamp),
                Tagging={
                    'TagSet': [
                        {
                            'Key': 'backup',
                            'Value': 'old'
                        }
                    ]
                }
            )


    def generate_and_push_backup(self):
        """
        Builds a backup archive from the server's active world and pushes it to
        S3. The server should not be running while this is executing.
        """
        pass


    def get_most_recent_backup_key(self):
        """
        Returns the key of the most recent backup in S3, or `None` if no
        backups are found.
        """
        # We have to sort the results ourselves
        obj_list = self.client.list_objects(Bucket=self.s3_bucket,
                                            Prefix=self._s3_backup_prefix)
        backups = [o['Key'] for o in obj_list.get('Contents', [])]
        backups.sort(reverse=True)

        # To ensure that the filename matches our format, iterate through our
        # sorted list until we find a filename match.
        for b in backups:
            if S3_BACKUP_RE.match(os.path.basename(b)):
                return b
        return None

    def _s3_backup_key(self, date):
        """
        Given a `date` datetime instance, returns an s3 key for that backup,
        including the .zip suffix.
        """
        return '{}-{}.zip'.format(self._s3_backup_prefix,
                                  date.strftime(S3_BACKUP_DATE_FMT))

    @property
    def _s3_backup_prefix(self):
        return '{}/backups/{}'.format(self.server_name, self.world_name)

    @property
    def _backup_path(self):
        return os.path.join(self.server_root_dir, 'backups', self.world_name)


def main():
    parser = ArgumentParser(
        description="Utilities for interacting with an S3 bucket storing " \
                    "Minecraft servers and backups.")
    parser.add_argument('--s3-bucket', nargs=1,
        help='Name of the S3 bucket to push to and pull from.')
    parser.add_argument('--server-name', nargs=1,
        help='Name of the Minecraft server directory in S3')

    args = parser.parse_args()
    p = Prospector(args.s3_bucket[0],
                   args.server_name[0],
                   'dangerworld',
                   '/home/josh/new-server')
    print p.get_most_recent_backup_key()

    p.fetch_most_recent_backup()

    p.push_most_recent_backup()

    """
    args = parser.parse_args()
    if args.command == 'fetch':
        fetch(args)
    """



if __name__ == '__main__':
    main()
