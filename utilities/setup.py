#!/usr/bin/env python
"""
Populates config templates based on user input.
"""

import sys
from argparse import ArgumentParser
from collections import defaultdict

from jinja2 import Environment, FileSystemLoader


TYPE_NAMES = {
    float: 'number',
    int: 'integer',
    str: 'string'
}


def prompt_boolean(description):
    """
    Prompts the user with the given `description` and returns a boolean
    indicating whether the answer was yes (True) or no (False).
    """
    answer = raw_input(description + ' [yN] ') 
    return answer and answer.lower() in ('yes', 'y')


def prompt_type(description, value_type, default=None):
    """
    Prompts the user with the given `description`, defaulting to `default` if
    no input is given. User will be reprompted if input is empty and no
    `default is given, or if input is not castable to `value_type`.
    """

    prompt = [description]
    if default is not None:
        prompt.append(' [{}]'.format(default))
    prompt.append(': ')
    prompt = ''.join(prompt)

    while True:
        value = raw_input(prompt) or default
        if value is None:
            continue

        if not isinstance(value, value_type):
            try:
                # Attempt to cast
                value = value_type(value)
            except ValueError:
                print("{} is not a {}".format(value, TYPE_NAMES[value_type]))
                continue
        break

    return value


def main():
    parser = ArgumentParser(
        description="Populates configs based on user input.")

    # Tuples consisting of:
    # 1. Dictionary name
    # 2. Key name 
    # 3. Expected type
    # 4. Default (or None)
    # 5. Description (presented to the user)
    settings = (
        ('aws', 'profile', str, 'minecraft', 'AWS profile to use'),
        ('aws', 's3_bucket', str, None, 'Name of the S3 bucket to use (must be globally unique)'),
        ('aws', 'max_spot_price', float, 0.05, 'Maximum amount to pay per spot instance per hour'),
        ('aws', 'region', str, 'us-east-1', 'AWS region to use'),
        ('aws', 'availability_zone', str, 'us-east-1e', 'AWS availability zone to use'),
        ('aws', 'instance_type', str, None, 'EC2 instance type to use'),
        ('aws', 'instance_tag', str, 'minecraft', 'AWS tag to use on minecraft EC2 instances'),
        ('aws', 'eip_alloc_id', str, '', "AWS elastic IP allocation ID (optional)"),
        ('server', 'hostname', str, '', "Server hostname, like 'minecraft.daftcyb.org' (optional)"),
        ('server', 'port', int, 25565, 'Port number server listens on'),
        ('server', 'root_dir', str, '/minecraft', 'Root directory to install minecraft to on the server'),
        ('server', 'name', str, None, 'Minecraft server name'),
        ('server', 'world_name', str, None, 'Minecraft world name (should match server.properties)'),
        ('server', 'base', str, None, 'Server base archive name in S3')
    )
    
    variables = defaultdict(dict)
    for key, subkey, value_type, default, description in settings:
        value = prompt_type(description, value_type, default)
        variables[key][subkey] = value
    
    # Force the user to review their settings
    print('Templates will be populated with the following settings:\n')
    for group_key, group_value in variables.items():
        print(group_key)
        for k, v in group_value.items():
            print('    {}: {}'.format(k, v))
    print('') 

    yes = prompt_boolean('Are the above settings correct?')
    if not yes:
        print('No changes have been persisted')
        sys.exit(1)

    # Populate the templates
    env = Environment(loader=FileSystemLoader('.'), autoescape=True)

    templates = ['terraform/variables.tf.j2', 'ansible/group_vars/all.j2']
    for template_path in templates:
        template = env.get_template(template_path)

        populated_path = template_path[:-3]
        with open(populated_path, 'w') as f:
            f.write(template.render(**variables))

        print('{} written'.format(populated_path))


if __name__ == '__main__':
    main()
