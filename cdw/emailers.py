"""
    :copyright: (c) 2011 Local Projects, all rights reserved
    :license: Affero GNU GPL v3, see LEGAL/LICENSE for more details.
"""
import types
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE

from boto.ses import SESConnection
from flask import current_app

class AmazonSender(object):

    def __init__(self, smtp_server, smtp_sender):
        self.smtp_server = smtp_server
        self.smtp_sender = smtp_sender

    def send_email(self, sender,
                         to_addresses,
                         subject,
                         text,
                         html=None,
                         reply_addresses=None,
                         sender_ascii=None):
        if current_app.config['ENVIRONMENT'] == 'development':
            current_app.logger.debug('No email will be sent in development mode')
            return
        
        if not sender_ascii:
            sender_ascii = sender

        message = MIMEMultipart('alternative')
        message.set_charset('UTF-8')

        message['Subject'] = _encode_str(subject)
        message['From'] = _encode_str(sender)
        message['To'] = _convert_to_strings(to_addresses)

        if reply_addresses:
            message['Reply-To'] = _convert_to_strings(reply_addresses)

        message.attach(MIMEText(_encode_str(text), 'plain'))

        if html:
            message.attach(MIMEText(_encode_str(html), 'html'))
        
        result = True
        server = smtplib.SMTP("smtp.ilstu.edu", 25)
        server.ehlo()
        try:
            server.sendmail(message['From'], message['To'], ("Subject: %s\r\n\r\n%s" % (message['Subject'], text)))
        except:

            result = False
        server.quit()
        return result


#--- Helpers ----------------------------------------------
def _convert_to_strings(list_of_strs):
    if isinstance(list_of_strs, (list, tuple)):
        result = COMMASPACE.join(list_of_strs)
    else:
        result = list_of_strs
    return _encode_str(result)

def _encode_str(s):
    if type(s) == types.UnicodeType:
        return s.encode('utf8')
    return s


def send_contact(**kwargs):
    msg = """
First Name: %(firstname)s
Last Name: %(lastname)s
Email: %(email)s
Feedback Type: %(feedback)s

Comment:
%(comment)s
"""
    contact_email = current_app.config['CDW']['contact_email']
    current_app.emailer.send_email(
        contact_email,
        [contact_email],
        'ILSTU Views Contact Form: %s' % kwargs['feedback'],
        msg % kwargs)
    
def send_forgot_password(recipient, reset_token):
    msg = """
To reset your password at ilstuviews.illinoisstate.edu, please go to the following link:

http://ilstuviews.illinoisstate.edu/forgot/%s

If you did not request your password to be reset, please ignore this email.
"""
    contact_email = current_app.config['CDW']['contact_email']
    current_app.emailer.send_email(
        contact_email,
        [recipient],
        'Your password reset for ilstuviews.illinoisstate.edu',
        msg % reset_token)
    
def send_reply_notification(recipient, context):
    msg = """
%(message)s

Click the link below to view the debate:
%(local_request)s/questions/%(question_id)s/debates/%(thread_id)s

* Do not reply to this email *

Click the link below to unsubscribe from email notifications about this debate:
%(local_request)s/notifications/unsubscribe/%(user_id)s/%(thread_id)s

Click the link below to unsubscribe from all email notifications:
%(local_request)s/notifications/unsubscribe/%(user_id)s/all
"""

    msg_html = """
<p>%(message)s</p>
<p>&nbsp;</p>
<p><a href="%(local_request)s/questions/%(question_id)s/debates/%(thread_id)s">View this debate</a></p>
<p>&nbsp;</p>
<p><em>Do not reply to this email.</em></p>
<p><a href="%(local_request)s/notifications/unsubscribe/%(user_id)s/%(thread_id)s">Click here to unsubscribe from email notifications of this debate</a><br/>
<a href="%(local_request)s/notifications/unsubscribe/%(user_id)s/all">Click here to unsubscribe from all email notifications</a></p>
"""
    contact_email = current_app.config['CDW']['contact_email']
    current_app.emailer.send_email(
        contact_email,
        [recipient],
        'A user replied to a debate you are following',
        msg % context,
        html=msg_html % context)
    
def forgot_password():
    pass

def init(app):
    app.emailer = AmazonSender(app.config['LOG_EMAIL_SERVER'],
                               app.config['LOG_EMAIL_SENDER'])
