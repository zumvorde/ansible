#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2020, Univention GmbH
# Written by Lukas Zumvorde <zumvorde@univention.de>
# Based on univention_apps module written by Alexander Ulpts <ulpts@univention.de>

# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)


import sys
import os
import json
import tempfile
import platform
from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = '''
---
module: univention_apps
version_added: "0.1.1"
short_description: "Installs and removes apps on Univention Corporate Server"
extends_documentation_fragment: ''
description:
  - Allows ansible to control installation, removal and update of ucs-apps
notes:
  - none
requirements: [ ]
author: Stefan Ahrens
options:
  name:
    description:
    - 'The name of the app'
    required: true
  state:
    description:
    - 'The desired state of the app / present, or absent'
    required: true
  upgrade:
    description:
    - 'Upgrade the app if installed and upgradable'
    required: false
  auth_username:
    description:
    - 'The name of the user with witch to install apps (usually domain-admin)'
    required: true
  auth_password:
    description:
    - 'The password needed to install apps (usually domain-admin)'
    required: true
'''

EXAMPLES = '''
- univention_apps: name=wordpress state=present auth_password={{ pwd }} upgrade=True
'''

def check_ucs():
    ''' Check if system is actually UCS, return bool '''
    return platform.dist()[0].lower() == 'univention'

def ansible_exec(action, appname=None, keyfile=None, username=None):
    ''' runs ansible's run_command(), choose from actions install, remove, upgrade '''
    univention_app_cmd = {
            'list' : "univention-app list --ids-only",
            'info' : "univention-app info --as-json",
            'install' : "univention-app {} --noninteractive --username {} --pwdfile {} {}".format(action, username, keyfile, appname),
            'remove' : "univention-app {} --noninteractive --username {} --pwdfile {} {}".format(action, username, keyfile, appname),
            'upgrade' : "univention-app {} --noninteractive --username {} --pwdfile {} {}".format(action, username, keyfile, appname),
            }
    return module.run_command(univention_app_cmd[action])

def get_apps_status():
    ''' Get the status of available, installed and upgradable apps and return lists'''
    def get_app_list():
        ''' exec to get list of all available apps on this system '''
        return ansible_exec(action='list')[1]
    def get_app_info():
        ''' exec to get lists of installed and upgradable apps on this system '''
        app_info = ansible_exec(action='info')
        try:
            app_infos = json.loads(app_info[1])
        except Exception as e:
            module.fail_json(msg="unable to parse json: {}".format(e))
        return app_infos['installed'], app_infos['upgradable']

    global available_apps_list
    global installed_apps_list
    global upgradable_apps_list
    available_apps_list = get_app_list()
    installed_apps_list, upgradable_apps_list = get_app_info()

def check_app_present(_appname):
    ''' check if a given app is in installed_apps_list, return bool '''
    return _appname in available_apps_list and filter(lambda x: _appname in x, installed_apps_list)

def check_app_absent(_appname):
    ''' check if a given app is NOT in installed_apps_list, return bool '''
    return _appname in available_apps_list and not filter(lambda x: _appname in x, installed_apps_list)

def check_app_upgradeable(_appname):
    ''' check if a given app is in upgradable_apps_list, return bool '''
    return _appname in available_apps_list and filter(lambda x: _appname in x, upgradable_apps_list)

def generate_tmp_auth_file(_data):
    ''' generate a temporaty auth-file and return path, MUST BE DELETED '''
    fileTemp = tempfile.NamedTemporaryFile(delete = False, mode='w')
    fileTemp.write(_data)
    fileTemp.close()
    return fileTemp.name

def install_app(_appname, _authfile):
    ''' installs an app with given name and path to auth-file, uses ansible_exec()
        and returns tuple of exit-code and stdout '''
    return ansible_exec(action='install', appname=_appname, keyfile=_authfile)

def remove_app(_appname, _authfile):
    ''' removes an app with given name and path to auth-file, uses ansible_exec()
        and returns tuple of exit-code and stdout'''
    return ansible_exec(action='remove', appname=_appname, keyfile=_authfile)

def upgrade_app(_appname, _authfile):
    ''' upgrades an app with given name and path to auth-file, uses ansible_exec()
        and returns tuple of exit-code and stdout'''
    return ansible_exec(action='upgrade', appname=_appname, keyfile=_authfile)

def main():
    ''' main() is an entry-point for ansible which checks app-status and installs,
        upgrades, or removes the app based on ansible state and name-parameters '''
    global module # declare ansible-module and parameters globally
    module = AnsibleModule(
        argument_spec = dict(
            name = dict(
                type='str',
                required=True
                aliases=['app']
            ),
            state = dict(
                type='str',
                default='present',
                choices=['present', 'absent']
            ),
            upgrade = dict(
                type='bool',
                required=False,
                default=False
            ),
            auth_password = dict(
                type="str",
                required=True,
                no_log=True
            ),
            auth_username = dict(
                type="str",
                required=True
            ),
        )
    )

    # This module should only run on UCS-systems
    if not check_ucs():
        changed = False
        return module.exit_json(
            changed=changed,
            msg='Non-UCS-system detected. Nothing to do here.'
        )

    # gather infos and vars
    get_apps_status()
    app_status_target = module.params.get('state') # desired state of the app
    app_status_upgrade = module.params.get('upgrade') # upgrade app if installed
    app_name = module.params.get('name') # name of the app
    auth_password = module.params.get('auth_password') # password for domain-adimin
    # check states and explicitly check for presence and absence of app
    app_present = check_app_present(app_name)
    app_absent = check_app_absent(app_name)
    app_upgradeable = check_app_upgradeable(app_name)

    # some basic logic-checks
    if not app_absent and not app_present: # this means the app does not exist
        module.fail_json(msg="app {} does not exist. Please choose from following options:\n{}".format(app_name, str(available_apps_list)))
    if app_absent and app_present: # schroedinger's app-status
        module.fail_json(msg="an error occured while getting the status of {}".format(app_name))

    # upgrade, install or remove the app, or just do nothing at all and exit
    if app_status_target == 'present' and app_upgradeable and app_status_upgrade:
        #upgrade_app(app_name)
        auth_file = generate_tmp_auth_file(auth_password)
        try:
            _upgrade_app = upgrade_app(app_name, auth_file)
            if _upgrade_app[0] == 0:
                module.exit_json(changed=True, msg="App {} successfully upgraded.".format(app_name))
            else:
                module.fail_json(msg="an error occured while upgrading {}".format(app_name))
        finally:
            os.remove(auth_file)

    if app_status_target == 'present' and app_present:
        module.exit_json(changed=False, msg="App {} already installed. No change.".format(app_name))

    elif app_status_target == 'present' and not app_present:
        #install_app(app_name)
        auth_file = generate_tmp_auth_file(auth_password)
        try:
            _install_app = install_app(app_name, auth_file)
            if _install_app[0] == 0:
                module.exit_json(changed=True, msg="App {} successfully installed.".format(app_name))
            else:
                module.fail_json(msg="an error occured while installing {}".format(app_name))
        finally:
            os.remove(auth_file)

    elif app_status_target == 'absent' and app_present:
        #remove_app(app_name)
        auth_file = generate_tmp_auth_file(auth_password)
        try:
            _remove_app = remove_app(app_name, auth_file)
            if _remove_app[0] == 0:
                module.exit_json(changed=True, msg="App {} successfully removed.".format(app_name))
            else:
                module.fail_json(msg="an error occured while uninstalling {}".format(app_name))
        finally:
            os.remove(auth_file)

    elif app_status_target == 'absent' and app_absent:
        module.exit_json(changed=False, msg="App {} not installed. No change.".format(app_name))

    else: # just in case ...
        module.fail_json(msg="an unknown error occured while handling {}".format(app_name))



if __name__ == '__main__':
    main()
