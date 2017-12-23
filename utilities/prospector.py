#!/usr/bin/env python
"""
Deals with S3 interactions, including pulling the server, pushing backups,
tagging old backups to expire, and more.
"""

import logging
import os
import re
import shutil
import sys
from argparse import ArgumentParser
from ConfigParser import ConfigParser
from datetime import datetime, timedelta
from zipfile import ZipFile, BadZipfile

import boto3

# Logging
LOG_FORMAT = u'%(asctime)s [%(levelname)s] %(message)s'
logger = logging.getLogger('prospector')
logger.setLevel(logging.INFO)
logger.handlers = []
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(LOG_FORMAT)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Constants

# a list of regexes matching file names, and the date format string that can
# be matched against the first regex group.
BACKUP_FORMATS = [
    # Aroma backup format
    (re.compile('\w+-\w+-(\d{4}-\d{2}-\d{2}--\d{2}-\d{2}).zip'), '%Y-%m-%d--%H-%M'),
    # FTB Utilities backup format
    (re.compile('(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}).zip'), '%Y-%m-%d-%H-%M-%S')
]

S3_BACKUP_RE = re.compile('\w+-(\d{8}T\d{6}).zip')
S3_BACKUP_DATE_FMT = '%Y%m%dT%H%M%S'


class Prospector(object):
    """
    Deals with world backup, archival and retrieval from S3.
    """

    def __init__(self, server_name, world_name, server_root_dir, s3_bucket):
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
            tmp_path = os.path.join('/tmp', os.path.basename(key))
            logger.info("Downloading backup from s3://{}/{} to {}".format(self.s3_bucket,
                                                                          key,
                                                                          tmp_path))

            self.client.download_file(self.s3_bucket,
                                      key,
                                      tmp_path)

            try:
                with ZipFile(tmp_path, 'r') as z:
                    # This makes the assumption that the archive contains the world
                    # as a subfolder, so it extracts correctly.
                    z.extractall(os.path.join(self.server_root_dir,
                                              self.server_name))
            except BadZipfile:
                logger.error("Zipfile is bad!")

            # Cleanup
            os.remove(tmp_path)
        else:
            logger.warning("No backups found!")


    def push_most_recent_backup(self, zipfile=None):
        """
        Uploads `zipfile` to s3 as a named backup, or checks for the most
        recent backup in the server's backup directory and pushes it to S3 if
        it hasn't already been uploaded. If a `zipfile` is used, the last
        modified time of the archive is used when naming the backup.
        """
        if not zipfile:
            # Only search for a backup if one isn't specified

            latest_path = None
            latest_stamp = None
            for root, dirs, files in os.walk(self.local_backup_path):
                # Look into the <world_name> subdirectory for backups too, if
                # such a directory exists. Do this by editing the list of
                # directories in-place.
                if self.world_name in dirs and root == self.local_backup_path:
                    for i, d in reversed(list(enumerate(dirs))):
                        if d != self.world_name:
                            del dirs[i]

                # Check each file to determine whether it matches one of our
                # known backup formats.
                for f in files:
                    # Check the filename against our known backup formats
                    result = None
                    for file_re, date_fmt in BACKUP_FORMATS:
                        result = file_re.match(f)
                        if result:
                            break

                    if result:
                        backup_time = datetime.strptime(result.group(1),
                                                        date_fmt)
                        if not latest_stamp or latest_stamp < backup_time:
                            latest_stamp = backup_time
                            latest_path = os.path.join(root, f)

            if not latest_path:
                logger.info("No periodic backups found")
                return
        else:
            latest_path = zipfile
            latest_stamp = datetime.fromtimestamp(os.path.getmtime(zipfile))

        # Whether or not a backup has been explicitly set or we're comparing
        # periodic backups, we still do this lookup so we can retag the old
        # 'current' backup.
        latest_s3_key = self.get_most_recent_backup_key()
        latest_s3_stamp = None
        if latest_s3_key:
            result = S3_BACKUP_RE.match(os.path.basename(latest_s3_key))
            latest_s3_stamp = datetime.strptime(result.group(1),
                                                S3_BACKUP_DATE_FMT)

        if zipfile or not latest_s3_stamp or latest_stamp > latest_s3_stamp:
            new_s3_key = self.s3_backup_key(latest_stamp)
            logger.info("Uploading backup file {} to s3://{}/{}".format(latest_path,
                                                                        self.s3_bucket,
                                                                        new_s3_key))

            self.client.upload_file(latest_path, self.s3_bucket, new_s3_key)
            self.tag_s3_object(new_s3_key, backup='new')

            if latest_s3_stamp:
                # If we found an older backup, retag it since it's no longer
                # current
                self.tag_s3_object(latest_s3_key, backup='old')


    def push_current_backup(self):
        """
        Builds a backup archive from the server's active world and pushes it to
        S3. The server should not be running while this is executing.
        """
        key = self.s3_backup_key(datetime.now())
        tmp_path = os.path.join('/tmp', os.path.basename(key))
        logger.info("Archiving backup of current state of '{}' world to {}".format(self.world_name,
                                                                                   tmp_path))

        # Strip the suffix off tmp_path, because `shutil.make_archive` adds its
        # own when it creates the file.
        base_path = os.path.join(self.server_root_dir, self.server_name)
        shutil.make_archive(tmp_path[:-4], 'zip', base_path, self.world_name)

        # Create a key for the archive in S3 and upload it
        self.push_most_recent_backup(zipfile=tmp_path)
        os.remove(tmp_path)


    def get_most_recent_backup_key(self):
        """
        Returns the key of the most recent backup in S3, or `None` if no
        backups are found.
        """
        # We have to sort the results ourselves
        obj_list = self.client.list_objects(Bucket=self.s3_bucket,
                                            Prefix=self.s3_backup_prefix)
        backups = [o['Key'] for o in obj_list.get('Contents', [])]
        backups.sort(reverse=True)

        # To ensure that the filename matches our format, iterate through our
        # sorted list until we find a filename match.
        for b in backups:
            if S3_BACKUP_RE.match(os.path.basename(b)):
                return b
        return None


    def tag_s3_object(self, key, **kwargs):
        """
        Tag an s3 object identified by `key` with the key-value pairs in
        `kwargs`.
        """
        tags = [{ 'Key': k, 'Value': v } for k, v in kwargs.iteritems()]
        self.client.put_object_tagging(
            Bucket=self.s3_bucket,
            Key=key,
            Tagging={ 'TagSet': tags }
        )


    def s3_backup_key(self, date):
        """
        Given a `date` datetime instance, returns an s3 key for that backup,
        including the .zip suffix.
        """
        return '{}-{}.zip'.format(self.s3_backup_prefix,
                                  date.strftime(S3_BACKUP_DATE_FMT))

    @property
    def s3_backup_prefix(self):
        return '{}/backups/{}'.format(self.server_name, self.world_name)

    @property
    def local_backup_path(self):
        return os.path.join(self.server_root_dir,
                            self.server_name,
                            'backups')


def main():
    FETCH, BACKUP, BACKUP_CURRENT = 'fetch', 'backup', 'backup_current'

    parser = ArgumentParser(
        description="Utilities for interacting with an S3 bucket storing " \
                    "Minecraft servers and backups.")
    parser.add_argument('action', choices=(FETCH, BACKUP, BACKUP_CURRENT),
        help="The action to take: 'fetch' gets the most recent backup from " \
             "S3 and installs it, 'backup' pushes the most recent backup to " \
             "S3, and 'backup_current' creates a fresh backup from the " \
             "current world directory and pushes it (server should be off).")
    parser.add_argument('--cfg', nargs=1, default=['/minecraft/prospector.cfg'],
        help="Config file to read settings from.")
    parser.add_argument('--log', nargs=1, default=['/minecraft/prospector.log'],
        help="File to append log messages to.")

    args = parser.parse_args()

    # Parse out settings from the config file
    try:
        with open(args.cfg[0], 'r') as f:
            config = ConfigParser()
            config.readfp(f)
    except IOError:
        logger.error('Unable to open config file \'{}\''.format(args.cfg[0]))
        sys.exit(1)

    # Additional logging setup to log to the file of choice
    handler = logging.FileHandler(args.log[0], 'a')
    formatter = logging.Formatter(LOG_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Parse out interesting pairs into their proper types from the config file
    cfg = dict()
    cfg['s3_bucket'] = config.get('main', 's3_bucket')
    cfg['server_name'] = config.get('main', 'server_name')
    cfg['server_root_dir'] = config.get('main', 'server_root_dir')
    cfg['world_name'] = config.get('main', 'world_name')

    p = Prospector(**cfg)

    if args.action == FETCH:
        p.fetch_most_recent_backup()
    elif args.action == BACKUP:
        p.push_most_recent_backup()
    elif args.action == BACKUP_CURRENT:
        p.push_current_backup()


if __name__ == '__main__':
    main()
