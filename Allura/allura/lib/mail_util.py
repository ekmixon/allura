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
import re
import logging
import smtplib
import email.parser
from six.moves.email_mime_multipart import MIMEMultipart
from six.moves.email_mime_text import MIMEText
from email import header

import six
import tg
from paste.deploy.converters import asbool, asint, aslist
from formencode import validators as fev
from tg import tmpl_context as c
from tg import app_globals as g

from allura.lib.utils import ConfigProxy
from allura.lib import exceptions as exc
from allura.lib import helpers as h
from six.moves import map

log = logging.getLogger(__name__)

RE_MESSAGE_ID = re.compile(r'<(?:[^>]*/)?([^>]*)>')
config = ConfigProxy(
    common_suffix='forgemail.domain',
    common_suffix_alt='forgemail.domain.alternates',
    return_path='forgemail.return_path',
)
EMAIL_VALIDATOR = fev.Email(not_empty=True)


def Header(text, *more_text):
    '''Helper to make sure we encode headers properly'''
    if isinstance(text, header.Header):
        return text
    # email.header.Header handles str vs unicode differently
    # see
    # http://docs.python.org/library/email.header.html#email.header.Header.append
    if not isinstance(text, six.text_type):
        raise TypeError('This must be unicode: %r' % text)
    head = header.Header(text)
    for m in more_text:
        if not isinstance(m, six.text_type):
            raise TypeError('This must be unicode: %r' % text)
        head.append(m)
    return head


def AddrHeader(fromaddr):
    '''Accepts any of:
        Header() instance
        foo@bar.com
        "Foo Bar" <foo@bar.com>
    '''
    if isinstance(fromaddr, six.string_types) and ' <' in fromaddr:
        name, addr = fromaddr.rsplit(' <', 1)
        addr = f'<{addr}'
        addrheader = Header(name, addr)
        if str(addrheader).startswith('=?'):  # encoding escape chars
            # then quoting the name is no longer necessary
            name = name.strip('"')
            addrheader = Header(name, addr)
    else:
        addrheader = Header(fromaddr)
    return addrheader


def is_autoreply(msg):
    '''Returns True, if message is an autoreply

    Detection based on suggestions from
    https://github.com/opennorth/multi_mail/wiki/Detecting-autoresponders
    '''
    h = msg['headers']
    return (
        h.get('Auto-Submitted') == 'auto-replied'
        or h.get('X-POST-MessageClass') == '9; Autoresponder'
        or h.get('Delivered-To') == 'Autoresponder'
        or h.get('X-FC-MachineGenerated') == 'true'
        or h.get('X-AutoReply-From') is not None
        or h.get('X-Autogenerated') in ['Forward', 'Group', 'Letter', 'Mirror', 'Redirect', 'Reply']
        or h.get('X-Precedence') == 'auto_reply'
        or h.get('Return-Path') == '<>'
    )


def parse_address(addr):
    userpart, domain = addr.split('@')
    # remove common domain suffix
    for suffix in [config.common_suffix] + aslist(config.common_suffix_alt):
        if domain.endswith(suffix):
            domain = domain[:-len(suffix)]
            break
    else:
        raise exc.AddressException(f'Unknown domain: {domain}')
    path = '/'.join(reversed(domain.split('.')))
    project, mount_point = h.find_project(f'/{path}')
    if project is None:
        raise exc.AddressException(f'Unknown project: {domain}')
    if len(mount_point) != 1:
        raise exc.AddressException(f'Unknown tool: {domain}')
    with h.push_config(c, project=project):
        app = project.app_instance(mount_point[0])
        if not app:
            raise exc.AddressException(f'Unknown tool: {domain}')
    return userpart, project, app


def parse_message(data):
    # Parse the email to its constituent parts

    # https://bugs.python.org/issue25545 says
    # > A unicode string has no RFC defintion as an email, so things do not work right...
    # > You do have to conditionalize your 2/3 code to use the bytes parser and generator if you are dealing with 8-bit
    # > messages. There's just no way around that.
    if six.PY2:
        parser = email.feedparser.FeedParser()
        parser.feed(data)
        msg = parser.close()
    else:
        # works the same as BytesFeedParser, and better than non-"Bytes" parsers for some messages
        parser = email.parser.BytesParser()
        msg = parser.parsebytes(data.encode('utf-8'))
    # Extract relevant data
    result = {}
    result['multipart'] = multipart = msg.is_multipart()
    result['headers'] = dict(msg)
    result['message_id'] = _parse_message_id(msg.get('Message-ID'))
    result['in_reply_to'] = _parse_message_id(msg.get('In-Reply-To'))
    result['references'] = _parse_message_id(msg.get('References'))
    if result['message_id'] == []:
        result['message_id'] = h.gen_message_id()
    else:
        result['message_id'] = result['message_id'][0]
    if multipart:
        result['parts'] = []
        for part in msg.walk():
            dpart = dict(
                headers=dict(part),
                message_id=result['message_id'],
                in_reply_to=result['in_reply_to'],
                references=result['references'],
                content_type=part.get_content_type(),
                filename=part.get_filename(None),
                payload=part.get_payload(decode=True))
            # payload is sometimes already unicode (due to being saved in mongo?)
            if part.get_content_maintype() == 'text':
                dpart['payload'] = six.ensure_text(dpart['payload'])
            result['parts'].append(dpart)
    else:
        result['payload'] = msg.get_payload(decode=True)
        # payload is sometimes already unicode (due to being saved in mongo?)
        if msg.get_content_maintype() == 'text':
            result['payload'] = six.ensure_text(result['payload'])

    return result


def identify_sender(peer, email_address, headers, msg):
    from allura import model as M
    # Dumb ID -- just look for email address claimed by a particular user
    addr = M.EmailAddress.get(email=email_address, confirmed=True)
    if addr and addr.claimed_by_user_id:
        return addr.claimed_by_user() or M.User.anonymous()
    from_address = headers.get('From', '').strip()
    if not from_address:
        return M.User.anonymous()
    addr = M.EmailAddress.get(email=from_address)
    if addr and addr.claimed_by_user_id:
        return addr.claimed_by_user() or M.User.anonymous()
    return M.User.anonymous()


# http://www.jebriggs.com/blog/2010/07/smtp-maximum-line-lengths/
MAX_MAIL_LINE_OCTETS = 990


def encode_email_part(content, content_type):
    try:
        # simplest email - plain ascii
        encoded_content = content.encode('ascii')
        encoding = 'ascii'
    except Exception:
        # utf8 will get base64 encoded so we only do it if ascii fails
        encoded_content = content.encode('utf-8')
        encoding = 'utf-8'

    for line in encoded_content.splitlines():
        if len(line) > MAX_MAIL_LINE_OCTETS:
            # switch to Quoted-Printable encoding to avoid too-long lines
            # we could always Quoted-Printabl, but it makes the output a little messier and less human-readable
            # the particular order of all these operations seems to be very important for everything to end up right
            msg = MIMEText('', content_type)
            msg.replace_header('content-transfer-encoding', 'quoted-printable')
            cs = email.charset.Charset('utf-8')
            cs.header_encoding = email.charset.QP
            cs.body_encoding = email.charset.QP
            payload = cs.body_encode(content.encode('utf-8'))
            msg.set_payload(payload, 'utf-8')
            return msg
    return MIMEText(encoded_content, content_type, encoding)


def make_multipart_message(*parts):
    msg = MIMEMultipart('related')
    msg.preamble = 'This is a multi-part message in MIME format.'
    alt = MIMEMultipart('alternative')
    msg.attach(alt)
    for part in parts:
        alt.attach(part)
    return msg


def _parse_message_id(msgid):
    if msgid is None:
        return []
    return [mo.group(1)
            for mo in RE_MESSAGE_ID.finditer(msgid)]


def _parse_smtp_addr(addr):
    addr = str(addr)
    addrs = _parse_message_id(addr)
    if addrs and addrs[0]:
        return addrs[0]
    return addr if '@' in addr else g.noreply


def isvalid(addr):
    '''return True if addr is a (possibly) valid email address, false
    otherwise'''
    try:
        EMAIL_VALIDATOR.to_python(addr, None)
        return True
    except fev.Invalid:
        return False


class SMTPClient(object):

    def __init__(self):
        self._client = None

    def sendmail(
            self, addrs, fromaddr, reply_to, subject, message_id, in_reply_to, message,
            sender=None, references=None, cc=None, to=None):
        if not addrs:
            return
        if to:
            message['To'] = AddrHeader(h.really_unicode(to))
        else:
            message['To'] = AddrHeader(reply_to)
        message['From'] = AddrHeader(fromaddr)
        message['Reply-To'] = AddrHeader(reply_to)
        message['Subject'] = Header(subject)
        message['Message-ID'] = Header(f'<{message_id}>')
        message['Date'] = email.utils.formatdate()
        if sender:
            message['Sender'] = AddrHeader(sender)
        if cc:
            message['CC'] = AddrHeader(cc)
            addrs.append(cc)
        if in_reply_to:
            if not isinstance(in_reply_to, six.string_types):
                raise TypeError('Only strings are supported now, not lists')
            message['In-Reply-To'] = Header(f'<{in_reply_to}>')
            if not references:
                message['References'] = message['In-Reply-To']
        if references:
            references = [f'<{r}>' for r in aslist(references)]
            message['References'] = Header(*references)
        content = message.as_string()
        smtp_addrs = list(map(_parse_smtp_addr, addrs))
        smtp_addrs = [a for a in smtp_addrs if isvalid(a)]
        if not smtp_addrs:
            log.warning('No valid addrs in %s, so not sending mail',
                        list(map(six.text_type, addrs)))
            return
        try:
            self._client.sendmail(
                config.return_path,
                smtp_addrs,
                content)
        except Exception:
            self._connect()
            self._client.sendmail(
                config.return_path,
                smtp_addrs,
                content)

    def _connect(self):
        if asbool(tg.config.get('smtp_ssl', False)):
            smtp_client = smtplib.SMTP_SSL(
                tg.config.get('smtp_server', 'localhost'),
                asint(tg.config.get('smtp_port', 25)),
                timeout=float(tg.config.get('smtp_timeout', 10)),
            )
        else:
            smtp_client = smtplib.SMTP(
                tg.config.get('smtp_server', 'localhost'),
                asint(tg.config.get('smtp_port', 465)),
                timeout=float(tg.config.get('smtp_timeout', 10)),
            )
        if tg.config.get('smtp_user', None):
            smtp_client.login(tg.config['smtp_user'],
                              tg.config['smtp_password'])
        if asbool(tg.config.get('smtp_tls', False)):
            smtp_client.starttls()
        self._client = smtp_client
