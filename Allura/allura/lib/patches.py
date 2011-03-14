import webob
import tg.decorators
from pylons import request

from allura.lib import helpers as h

def apply():
    old_lookup_template_engine = tg.decorators.Decoration.lookup_template_engine

    @h.monkeypatch(tg.decorators.Decoration)
    def lookup_template_engine(self, request):
        '''Wrapper to handle totally borked-up HTTP-ACCEPT headers'''
        try:
            return old_lookup_template_engine(self, request)
        except:
            pass
        environ = dict(request.environ, HTTP_ACCEPT='*/*')
        request = webob.Request(environ)
        return old_lookup_template_engine(self, request)

    @h.monkeypatch(tg, tg.decorators)
    def override_template(controller, template):
        '''Copy-pasted patch to allow multiple colons in a template spec'''
        if hasattr(controller, 'decoration'):
            decoration = controller.decoration
        else:
            return
        if hasattr(decoration, 'engines'):
            engines = decoration.engines
        else:
            return

        for content_type, content_engine in engines.iteritems():
            template = template.split(':', 1)
            template.extend(content_engine[2:])
            try:
                override_mapping = request._override_mapping
            except AttributeError:
                override_mapping = request._override_mapping = {}
            override_mapping[controller.im_func] = {content_type: template}
