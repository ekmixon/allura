#       Licensed to the Apache Software Foundation (ASF) under one
#       or more contributor license agreements.  See the NOTICE file
#       distributed with this work for additional information
#       regarding copyright ownership.  The ASF licenses this file
#       to you under the Apache License, Version 2.0 (the
#       "License"); you may not use this file except in compliance
#       with the License.  You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#       Unless required by applicable law or agreed to in writing,
#       software distributed under the License is distributed on an
#       "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#       KIND, either express or implied.  See the License for the
#       specific language governing permissions and limitations
#       under the License.

from __future__ import unicode_literals
from __future__ import absolute_import
import warnings

from tg import tmpl_context as c

from allura import model as M

from . import base


class RecloneRepoCommand(base.Command):
    min_args = 3
    max_args = None
    usage = '<ini file> [-n nbhd] <project_shortname> <mount_point>'
    summary = 'Reinitialize a repo from the original clone source'
    parser = base.Command.standard_parser(verbose=True)
    parser.add_option('-n', '--nbhd', dest='nbhd', type='string', default='p',
                      help='neighborhood prefix (default: p)')

    def command(self):
        self._setup()
        self._load_objects()
        self._clone_repo()

    def _setup(self):
        '''Perform basic setup, suppressing superfluous warnings.'''
        with warnings.catch_warnings():
            try:
                from sqlalchemy import exc
            except ImportError:
                pass
            else:
                warnings.simplefilter("ignore", category=exc.SAWarning)
            self.basic_setup()

    def _load_objects(self):
        '''Load objects to be operated on.'''
        c.user = M.User.query.get(username='sfrobot')
        nbhd = M.Neighborhood.query.get(url_prefix=f'/{self.options.nbhd}/')
        assert nbhd, f'Neighborhood with prefix {self.options.nbhd} not found'
        c.project = M.Project.query.get(
            shortname=self.args[1], neighborhood_id=nbhd._id)
        assert (
            c.project
        ), f'Project with shortname {self.args[1]} not found in neighborhood {nbhd.name}'

        c.app = c.project.app_instance(self.args[2])
        assert (
            c.app
        ), f'Mount point {self.args[2]} not found on project {c.project.shortname}'

    def _clone_repo(self):
        '''Initiate the repo clone.'''
        source_url = c.app.config.options.get('init_from_url')
        source_path = c.app.config.options.get('init_from_path')
        assert (
            source_url or source_path
        ), f'{c.app} does not appear to be a cloned repo'

        c.app.repo.init_as_clone(source_path, None, source_url)
