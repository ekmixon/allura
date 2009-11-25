import os
import mimetypes
import pkg_resources
from tg import expose, redirect, flash, config, validate, request, response
from webob import exc

from pyforge.lib.dispatch import _dispatch, default

class StaticController(object):
    '''Controller for mounting static resources in plugins by the plugin
    name'''

    def _dispatch(self, state, remainder):
        return _dispatch(self, state, remainder)
        
    def _lookup(self, ep_name, *remainder):
        for ep in pkg_resources.iter_entry_points('pyforge', ep_name):
            result = StaticAppController(ep)
            # setattr(self, ep_name, result)
            return result, ['default'] + list(remainder)
        raise exc.HTTPNotFound, ep_name
        

class StaticAppController(object):

    def __init__(self, ep):
        self.ep = ep
        self.fn = pkg_resources.resource_filename(
            ep.module_name, 'static/%s' % ep.name)

    @expose()
    def default(self, *args):
        # Stick the !@#$!@ extension back on args[-1]
        fn = request.path.rsplit('/', 1)[-1]
        ext = fn.rsplit('.', 1)[-1]
        args = list(args[:-1]) + [ args[-1] + '.' + ext ]
        path = os.path.join(self.fn, '/'.join(args))
        mtype, menc = mimetypes.guess_type(path)
        if mtype:
            response.headers['Content-Type'] = mtype
        if menc:
            response.headers['Content-Encoding'] = menc
        return open(path, 'rb')
