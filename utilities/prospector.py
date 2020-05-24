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
from tempfile import mkdtemp
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

# a list of regexes matching file names, and the date format string that can
# be matched against the first regex group.
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

    @property
    def s3_backup_prefix(self):
        return '{}/backups/{}'.format(self.server_name, self.world_name)

    @property
    def server_path(self):
        return os.path.join(self.server_root_dir, self.server_name)

    @property
    def world_path(self):
        return os.path.join(self.server_root_dir, self.server_name, self.world_name)

    @staticmethod
    def backup_time_from_key(backup_key):
        """
        Given a backup filename or S3 key, returns a `datetime` instance for
        that key's time.
        """
        fname = os.path.basename(backup_key)
        if fname.endswith('.zip'):
            fname = fname[:-4]
        date = fname.split('-')[1]
        return datetime.strptime(date, S3_BACKUP_DATE_FMT)

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

    def fetch_most_recent_backup(self):
        """
        Fetches the most recent backup in S3 and returns the local temporary
        file path.
        """
        key = self.get_most_recent_backup_key()

        # If a key isn't returned, there's nothing to do
        if key:
            tmp_path = os.path.join('/tmp', os.path.basename(key))
            logger.info("Downloading backup from s3://{}/{} to {}".format(
                self.s3_bucket,
                key,
                tmp_path
            ))

            self.client.download_file(self.s3_bucket, key, tmp_path)

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
            logger.warning("No backups found in S3")

    def upload_backup(self, zipfile):
        """
        Uploads `zipfile` to S3, stamping it using the current time. The
        previous most-recent backup in S3, if one exists, is re-tagged as old.
        """
        latest_path = zipfile
        latest_stamp = datetime.utcnow()

        # Whether or not a backup has been explicitly set or we're comparing
        # periodic backups, we still do this lookup so we can retag the old
        # 'current' backup.
        latest_s3_key = self.get_most_recent_backup_key()
        latest_s3_stamp = None
        if latest_s3_key:
            result = S3_BACKUP_RE.match(os.path.basename(latest_s3_key))
            latest_s3_stamp = datetime.strptime(result.group(1),
                                                S3_BACKUP_DATE_FMT)

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
        S3. The server must not be writing to disk while this is executing.
        """
        backup_path = self.create_current_backup()
        if not backup_path:
            logger.error('Unable to create backup')
        else:
            self.upload_backup(backup_path)
            shutil.rmtree(os.path.dirname(backup_path))

    def create_current_backup(self):
        """
        Creates a backup archive and returns the path.

        NOTE: Caller is responsible for removing the file and the directory
              when finished.
        """
        backup_path = os.path.join(
            mkdtemp(),
            os.path.basename(self.s3_backup_key(datetime.utcnow()))
        )

        with ZipFile(backup_path, 'w') as z:
           for folder, dirnames, files in os.walk(self.server_path):
               # If we're at the top (server-level), exclude everything except
               # the world directory
               if folder == self.server_path:
                   if self.world_name not in dirnames:
                       logger.error("No world directory '{}' present in server directory {}".format(self.world_name, self.server_path))
                       os.rmdir(os.path.dirname(backup_path))
                       return
                   else:
                       # In-place removal of all directories beyond the first,
                       # which is set to the world directory name
                       for i in range(len(dirnames) - 1, 0, -1):
                           dirnames.pop(i)
                       dirnames[0] = self.world_name
                       continue  # Don't grab any files from the base directory

               archive_dir = folder.replace(self.server_path, '')
               for file_name in files:
                   file_path = os.path.join(folder, file_name)
                   z.write(file_path, os.path.join(archive_dir, file_name))
                   logger.debug('Writing {} to archive as {}'.format(file_path, os.path.join(archive_dir, file_name)))

        return backup_path

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
        backup_key = None
        for b in backups:
            if S3_BACKUP_RE.match(os.path.basename(b)):
                backup_key = b
                break

        return backup_key


def main():
    FETCH, BACKUP = 'fetch', 'backup'

    parser = ArgumentParser(
        description="Utilities for interacting with Minecraft backups stored "
                    "in an S3 bucket.")
    parser.add_argument('action', choices=(FETCH, BACKUP),
        help="The action to take: 'fetch' gets the most recent backup from "
             "S3 and installs it, 'backup' creates an archive from the world "
             "directory and pushes it to S3 (server should not be writing to "
             "disk during creation).")
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
        p.push_current_backup()


if __name__ == '__main__':
    main()
