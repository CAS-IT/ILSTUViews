"""
    :copyright: (c) 2011 Local Projects, all rights reserved
    :license: Affero GNU GPL v3, see LEGAL/LICENSE for more details.
"""
import datetime
import random
import urllib
import bitlyapi
from cdw import utils
from auth import auth_provider
from cdw.forms import (UserRegistrationForm, SuggestQuestionForm, 
                       VerifyPhoneForm, EditProfileForm, 
                       ResetPasswordForm)
from cdw.models import PhoneVerificationAttempt, ShareRecord, Thread
from cdw.services import cdw, connection_service
from cdwapi import cdwapi 
from flask import (current_app, render_template, request, redirect,
                   session, flash, abort, jsonify)
from flaskext.login import login_required, current_user, login_user
from lib import facebook
from werkzeug.exceptions import BadRequest

def get_facebook_profile(token):
    graph = facebook.GraphAPI(token)
    return graph.get_object("me")

def init(app):
    @app.route("/")
    def index():
        debate_offset = session.pop('debate_offset', 'current')
        
        return render_template("index.html",
                               debate_offset=debate_offset, 
                               section_selector="home", 
                               page_selector="index")
    
    @app.route("/login")
    def login():
        form = auth_provider.login_form(request.args)
        return render_template("login.html", login_form=form, 
                               section_selector="login", page_selector="index")
    
    @app.route("/profile")
    @login_required
    def profile():
        # oddly needed for lookup
        user = cdw.users.with_id(current_user.get_id())
         
        threads = cdw.get_threads_started_by_user(current_user)[:5]
        all_posts = cdw.posts.with_fields(author=user).order_by('-created')
        debates = []
        
        for p in all_posts:
            try:
                debates.append(cdw.threads.with_firstPost(p))
            except:
                pass
            
        more_posts = len(all_posts) - 10
        more_debates = len(debates) - 10
        
        return render_template("profile.html",
                               section_selector="profile", 
                               page_selector="index",
                               threads=threads,
                               posts=all_posts[:10],
                               debates=debates[:10],
                               more_posts=more_posts,
                               more_debates=more_debates)
        
    @app.route("/profile/edit", methods=['GET','POST'])
    @login_required
    def profile_edit():
        user = current_user
        form = EditProfileForm()
        
        if request.method == 'POST' and form.validate():
            user = cdw.update_user_profile(user.get_id(),
                                           form.username.data,
                                           form.email.data,
                                           form.password.data)
            
            flash('Your profile has been updated.')
            return redirect('/profile')
            
        form.username.data = user.username
        form.email.data = user.email
        
        phoneForm = VerifyPhoneForm(csrf_enabled=False)
        phoneForm.phonenumber.data = user.phoneNumber
        
        return render_template("profile_edit.html", 
                               form=form,
                               phoneForm=phoneForm,
                               section_selector="profile", 
                               page_selector="edit")
        
    @app.route("/profile/photo", methods=['POST'])
    @login_required
    def profile_photo():
        try:
            current_app.user_profile_image_store.saveProfileImage(
                current_user, request.form.get('photo'))
            
            return jsonify(current_user.as_dict())
        except Exception, e:
            current_app.logger.error("Error saving profile image: %s" % e)
            abort(400)
    
    
    @app.route("/register", methods=['POST'])
    def register_post():
        if current_user.is_authenticated():
            return redirect("/")
        
        current_app.logger.debug('Attempting to register a user')
        
        # Always clear out any verified phone numbers
        #session.pop('verified_phone', None)
        
        form = UserRegistrationForm()
        
        if form.validate():
            # Register the user
            user = cdw.register_website_user(
                form.username.data, 
                form.email.data, 
                form.password.data, 
                session.pop('verified_phone', None)
            )
            
            # Try connecting their facebook account if a token
            # is in the session
            try:
                handler = current_app.social.facebook.connect_handler
                
                conn = handler.get_connection_values({
                    "access_token": session['facebooktoken'] 
                })
                
                conn['user_id'] = str(user.id)
                current_app.logger.debug('Saving connection: %s' % conn)
                connection_service.save_connection(**conn)
            except KeyError, e:
                current_app.logger.error(e)
                pass
            except Exception, e:
                current_app.logger.error(
                    'Could not save connection to Facebook: %s' % e)
                
            # Log the user in
            login_user(user)
            
            # Clear out the temporary facebook data
            session.pop('facebookuserid', None)
            session.pop('facebooktoken', None)
            
            # Send them to get their picture taken
            return redirect("/register/photo")
        
        current_app.logger.debug(form.errors)
        
        return render_template('register.html', 
                               section_selector="register", 
                               page_selector="email", 
                               form=form, 
                               show_errors=True,
                               phoneForm=VerifyPhoneForm(csrf_enabled=False))
        
    
    @app.route("/register/email", methods=['GET', 'POST'])
    def register_email():
        if current_user.is_authenticated():
            return redirect("/")
        
        form = UserRegistrationForm()
        # You'd think this wouldn't need to be called here but
        # a CSRF error will come up when the form is POSTed to 
        # /register. So below there's a show_errors flag in the
        # template context blow
        form.validate()
        
        # See if a password was passed from the register modal
        form.password.data = request.form.get('password', '')
        
        
        return render_template('register.html', 
                               section_selector="register", 
                               page_selector="email", 
                               form=form, 
                               show_errors=False,
                               phoneForm=VerifyPhoneForm(csrf_enabled=False))
    
    @app.route("/register/facebook", methods=['GET'])
    def register_facebook():
        if current_user.is_authenticated():
            return redirect("/")
        # Always clear out any verified phone numbers
        session.pop('verified_phone', None)
        
        # Try getting their facebook profile
        profile = get_facebook_profile(session['facebooktoken'])
        
        phoneForm = VerifyPhoneForm(csrf_enabled=False)
        form = UserRegistrationForm(username=profile['first_name'], 
                                    email=profile['email'],
                                    csrf_enabled=False)
        
        form.password.data = request.form.get('password', '')
        form.validate()
        
        return render_template('register.html',
                               form=form, 
                               phoneForm=phoneForm,
                               facebook_profile=profile, 
                               show_errors=False,
                               section_selector="register", 
                               page_selector="facebook")
    
    @app.route("/register/photo")
    @login_required
    def register_photo():
        # If they set their phone number see if they used the kiosk
        # and use their photograph
        found_kiosk_image = False
        
        if current_user.phoneNumber and len(current_user.phoneNumber) > 1:
            current_app.logger.debug('The user set their phone number during '
                                     'the registration process. Check to see '
                                     'if they have used the kiosk before.')
            
            # Find the first kiosk user with the same phone number
            user = cdw.users.with_id(current_user.get_id())
            kiosk_user = cdw.users.with_fields(origin="kiosk", 
                    phoneNumber=current_user.phoneNumber).first()
                    
            if kiosk_user:
                current_app.logger.debug("Found a kiosk user with the same "
                                         "phone number. Check if the images "
                                         "have been uploaded to S3 yet...")
                import urllib2
                from boto.s3.connection import S3Connection
                
                try:
                    image_url = '%s/media/images/web/%s.jpg' % (current_app.config['MEDIA_ROOT'], str(kiosk_user.id))
                    image2_url = '%s/media/images/thumbnails/%s.jpg' % (current_app.config['MEDIA_ROOT'], str(kiosk_user.id))
                    current_app.logger.debug("Checking if %s exists" % image_url)
                    urllib2.urlopen(image_url)
                    current_app.logger.debug("Checking if %s exists" % image2_url)
                    urllib2.urlopen(image2_url)
                    
                    aws_conf = current_app.config['CDW']['aws']
                    key_id = aws_conf['access_key_id']
                    secret_key = aws_conf['secret_access_key']
                    bucket_name = aws_conf['s3bucket']
                    
                    conn = S3Connection(key_id, secret_key)
                    bucket = conn.get_bucket(bucket_name)
                    
                    source_web_key = 'media/images/web/%s.jpg' % str(kiosk_user.id)
                    source_thumb_key = 'media/images/thumbnails/%s.jpg' % str(kiosk_user.id)
                    
                    new_web_key = 'images/users/%s-web.jpg' % str(user.id)
                    new_thumb_key = 'images/users/%s-thumbnail.jpg' % str(user.id)
                    
                    current_app.logger.debug("Copying web image %s to %s" % (source_web_key, new_web_key))
                    bucket.copy_key(new_web_key, bucket_name, source_web_key, preserve_acl=True)
                    
                    current_app.logger.debug("Copying thumbnail image %s to %s" % (source_thumb_key, new_thumb_key))
                    bucket.copy_key(new_thumb_key, bucket_name, source_thumb_key, preserve_acl=True)
                    
                    current_app.logger.debug("Setting user image")
                    current_user.webProfilePicture = user.webProfilePicture = '%s-web.jpg' % str(user.id)
                    current_user.webProfilePictureThumbnail = user.webProfilePictureThumbnail = '%s-thumbnail.jpg' % str(user.id)
                    user.save()
                    found_kiosk_image = True
                except Exception, e:
                    current_app.logger.warn("Unable to copy kiosk image for "
                                            "web user: %s" % e)
                
            
        return render_template('register_photo.html',
                               section_selector="register", 
                               page_selector="photo",
                               found_kiosk_image=found_kiosk_image)
        
    @app.route("/register/complete")
    @login_required
    def register_complete():
        return render_template('register_complete.html',
                               section_selector="register", 
                               page_selector="complete")
    
    
    @app.route("/privacy", methods=['GET'])
    def privacy():
        return render_template('privacy.html', 
                               section_selector="privacy", 
                               page_selector="index")
    
    @app.route("/contact", methods=['GET','POST'])
    def contact():
        from forms import ContactForm
        form = ContactForm()
        
        if request.method == 'POST' and form.validate():
            from cdw import emailers
            emailers.send_contact(**form.to_dict())    
            flash("Thank you for your feedback.")
        else:
            print form.errors
            
        return render_template('contact.html', 
                               section_selector="contact", 
                               page_selector="index",
                               form=form)
    
    
    @app.route("/suggest", methods=['GET','POST'])
    @login_required
    def suggest():
        form = SuggestQuestionForm(request.form) 
        
        if request.method == 'POST':
            if form.validate():
                form.to_question().save()
                flash('We have received your question. Thanks for the suggestion!');
        
        return render_template('suggest.html',
                               section_selector="suggest", 
                               page_selector="index",
                               form=form);
                               
    @app.route("/verify/phone", methods=['POST'])
    def verify_phone():
        session.pop('phone_verify_id', None)
        session.pop('verified_phone', None)
        
        form = VerifyPhoneForm(csrf_enabled=False)
        
        if form.validate():
            
            while(True):
                token = str(random.randint(100000, 999999))
                
                try:
                    # Make sure a random token doesn't exist yet
                    current_app.cdw.phoneverifications.with_token(token)
                except:
                    expires = (datetime.datetime.utcnow() + 
                               datetime.timedelta(minutes=5))
                    
                    phone = utils.normalize_phonenumber(form.phonenumber.data)
                    
                    pva = PhoneVerificationAttempt(expires=expires, 
                                                   token=token, 
                                                   phoneNumber=phone)
                    
                    current_app.cdw.phoneverifications.save(pva)
                    session['phone_verify_id'] = str(pva.id)
                    
                    current_app.logger.debug(
                        'Saved phone number verification attempt: %s' % pva)
                    
                    break # out of the while loop
                
            try:
                config = current_app.config['CDW']['twilio']
                sender = config['switchboard_number']
                current_app.twilio.send_message(pva.token, sender, [phone])
                return jsonify({"success": True})
            except Exception, e:
                return jsonify({"success": False, "error": '%s' % e})
            
            
        
        current_app.logger.debug(form.phonenumber.errors)
        return jsonify({"success": False, "error": form.phonenumber.errors[0]})
    
    @app.route("/verify/code", methods=['POST'])
    def verify_code():
        session.pop('verified_phone', None)
        msg = 'no match'
        
        try:
            pva_id = session['phone_verify_id']
            pva = current_app.cdw.phoneverifications.with_id(pva_id)
            
            if pva.expires < datetime.datetime.utcnow():
                msg = 'expired'
            
            if request.form['code'] == pva.token:
                session.pop('phone_verify_id', None)
                
                if current_user.is_authenticated():
                    current_user.phoneNumber = pva.phoneNumber
                    cdw.users.save(current_user)
                    
                else:
                    # Save it in the session for a little bit
                    # in case this is a registration process
                    session['verified_phone'] = pva.phoneNumber
                
                current_app.logger.debug(
                    'Verified phone number: %s' % pva.phoneNumber)
                
                return 'success'
            
        except:
            pass
            
        raise BadRequest(msg)
    
    @app.route("/questions/<question_id>")
    def question_show(question_id):
        try:
            cdw.questions.with_id(question_id)
            return redirect('/#/questions/%s' % question_id)
        except:
            abort(404)
        
    
    @app.route("/questions/<question_id>/debates/<debate_id>")
    def debate_show(question_id, debate_id):
        try:
            cdw.questions.with_id(question_id)
            cdw.threads.with_id(debate_id)
            session['debate_offset'] = debate_id
            return redirect('/#/questions/%s/debates/%s' % 
                            (question_id, debate_id))
        except Exception, e:
            abort(404)
    
    @app.route("/questions/archive")
    def questions_archive():
        now = datetime.datetime.utcnow()
        questions = cdw.questions.with_fields(archived=True)
        q_context = []
        
        for q in questions:
            likes = 0
            threads = cdw.threads.with_fields(question=q)
            
            for t in threads:
                likes += t.firstPost.likes
                
                posts = cdw.posts.with_fields(thread=t)
                
                for p in posts[1:]:
                    likes += p.likes
                
            q_context.append(dict(question=q, likes=likes))
        
        return render_template('questions_archive.html', 
                               questions=q_context,
                               categories=cdw.categories.all(),
                               section_selector="questions", 
                               page_selector="archive")
        
    @app.route("/questions/archive/<category_id>")
    def questions_archive_category(category_id):
        try:
            cat = cdw.categories.with_id(category_id)
            questions = cdw.questions.with_fields(archived=True, category=cat)
            return render_template('questions_archive.html', 
                                   current_category=cat,
                                   questions=questions,
                                   categories=cdw.categories.all(),
                                   section_selector="questions", 
                                   page_selector="archive")
        except Exception, e:
            current_app.logger.error("Error getting archive category: %s" % e)
            abort(404)
        
    @app.route("/share/<provider_id>/<debate_id>")
    def share(provider_id, debate_id):
        if provider_id not in ['facebook','twitter']:
            abort(404)
            
        try:
            thread = cdw.threads.with_id(debate_id)
        except:
            abort(404)
            
        record = ShareRecord(provider=provider_id, debateId=debate_id)
        record.save()
        
        config = current_app.config
        lr = config['LOCAL_REQUEST']
        question_id = str(thread.question.id)
        
        url = "%s/questions/%s/debates/%s" % (lr, question_id, debate_id)
        
        username = config['CDW']['bitly']['username']
        api_key = config['CDW']['bitly']['api_key']
        
        b = bitlyapi.BitLy(username, api_key)
        res = b.shorten(longUrl=url)
        short_url = res['url']
        
        if provider_id == 'facebook':
            msg = "I just debated at CDW"
            # TODO: Ugly, make nicer
            app_id = config['SOCIAL_PROVIDERS']['facebook']['oauth']['consumer_key']
            
            fb_url = "http://www.facebook.com/dialog/feed?" \
                     "app_id=%s" \
                     "&link=%s" \
                     "&name=%s" \
                     "&description=%s" \
                     "&message=%s" \
                     "&redirect_uri=%s" \
                     "&display=page"

            redirect_url = urllib.quote_plus('%s/share/close' % lr)
            fb_url = fb_url % (app_id, 
                               urllib.quote_plus(url),
                               urllib.quote_plus('ILSTU Views'),
                               urllib.quote_plus('A place for civil debate'), 
                               urllib.quote_plus(msg), 
                               redirect_url)
            
            current_app.logger.debug(fb_url)
            
            return redirect(fb_url)
            
        if provider_id == 'twitter':
            msg = "I just debated on ILSTU Views. %s" % short_url
            msg = urllib.quote_plus(msg)
            return redirect('http://twitter.com/home?status=%s' % msg)
            
    @app.route('/share/close')
    def share_close():
        """A callback to close the window from sharing on facebook"""
        return render_template("close.html")
    
    @app.route('/forgot', methods=['POST'])
    def forgot():
        email = request.form.get('email', None)
        
        if email:
            try:
                user = cdw.users.with_email(email)
            except Exception, e:
                return jsonify({"success": False})
            
            user.create_reset_token()
            from cdw import emailers
            emailers.send_forgot_password(user.email, user.reset_token)
            return jsonify({"success": True})
    
    @app.route("/forgot/<reset_token>")
    def forgot_token(reset_token):
        error = ""
        form = ResetPasswordForm()
        user = ""
        try:
            user = cdw.users.with_reset_token(reset_token)
            valid_token = True
        except Exception, e:
            valid_token = False
        
        return render_template("/forgot_token.html", error=error, form=form, stepone=True, reset_token=reset_token, valid_token=valid_token, user=user)

    @app.route("/forgot_reset", methods=['POST'])
    def forgot_token_reset():
        error = ""
        reset_token = request.form.get('reset_token', None)
        form = ResetPasswordForm()
        try:
            user = cdw.users.with_reset_token(reset_token)
            cdw.reset_user_password(user.get_id(), form.new_password.data)
        except Exception, e:
            error = e

        return render_template("/forgot_token.html", error=error, stepone=False)

    @app.route("/whatisthis")
    def whatisthis():
        return render_template("/whatisthis.html",
                               section_selector="whatisthis", 
                               page_selector="index",)
        
    @app.route("/notifications/unsubscribe/<user_id>/all")
    def unsubscribe_all(user_id):
        try:
            user = cdw.users.with_id(user_id)
            cdwapi.stop_all_email_updates(user)
        except Exception, e:
            current_app.logger.error("Error unsubscribing user from all email "
                               "notifications: %s" % e)
            
        return "You will no longer receive email updates for any debates."
            
    @app.route("/notifications/unsubscribe/<user_id>/<thread_id>")
    def unsubscribe_one(user_id, thread_id):
        try:
            user = cdw.users.with_id(user_id)
            thread = cdw.threads.with_id(thread_id)
            cdwapi.stop_email_updates(user, thread)
        except Exception, e:
            current_app.logger.error("Error unsubscribing user from notifications "
                               "for specific thread: %s" % e)
            
        return "You will no longer receive email updates for this debate."
    
    """        
    @app.route("/press")
    def press():
        return render_template("press.html",
                               section_selector="press", 
                               page_selector="index")
    """   
         
    @app.route("/channel")
    def channel():
        return render_template("/channel.html")
