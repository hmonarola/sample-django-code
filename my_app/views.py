from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os
import uuid
import stripe
from django.conf import settings
from .models import (Subscriptions, Users, UserCards, SubscriptionHistory, DiscountCodes, 
                     SubscriptionFees)
from django.http import HttpResponse
from django.template.loader import render_to_string
import boto3
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
from email.mime.image import MIMEImage
from django.core.mail import EmailMultiAlternatives
from urllib import parse
import requests, json
from django.core.cache import cache
from .schedules import scheduler

from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
from django.utils.timezone import make_aware
from django.utils import timezone

logger = logging.getLogger("apis.views")

stripe.api_key = os.environ.get('STRIPE_APP_SECRET')
KB = 1024
MB = KB * KB
config = TransferConfig(multipart_threshold=99*MB, use_threads=True)
bucket_name = os.environ.get('BUCKET_NAME')


load_dotenv()
# Create your views here.
# scheduler.start()

@csrf_exempt
def load_conversation_details(request, audio_id=""):
    if request.method == "GET":
        if audio_id == "":
            audio_id = 0
        context = {
            'audio_id': audio_id,
            "APP_URL": os.environ.get('FRONTEND'),
            "DOMAIN_URL": os.environ.get('DOMAIN_URL'),
            "AI_API":os.environ.get('AI_API'),
            "esecretKey": os.environ.get('ENCRIPTION_SECRET_KEY')
        }
        return render(request, 'after-login/conversation_result.html', context)
    elif request.method == "POST":
        try:
        # group_name = request.POST['user_id'] + '_' + request.POST['patient_id'] + '_' + str(uuid.uuid4())
            file = request.FILES['file_upload']
            s3 = boto3.client('s3')
            actual_name = file.name.split('.')[0]
            extension = file.name.split('.')[-1]
            new_name = actual_name + '_' + str(uuid.uuid4()) + '.' + extension
            if not os.path.isdir('uploads'):
                os.makedirs('uploads')
            file_key = "inputaudios/"+file.name
            filename = os.path.join('uploads',file.name)
            with open(filename, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
            response = s3.upload_file(filename, bucket_name, file_key, Config=config)
            os.remove(filename)
            context = {
                "file_key": file_key,
                "DOMAIN_URL": os.environ.get('DOMAIN_URL'),
                "patient_id": request.POST['patient_id']
            }
            return JsonResponse(context)
        except Exception as e:
            logger.info("Error in file upload to aws!")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")
            # closing the file
            f.close()
            return JsonResponse({}, status=400)
    
def load_subscription_page(request):
    prod_query = "metadata['created_by']:'stripeui'"
    prices = stripe.Price.search(query=prod_query, expand=["data.product"], limit=100)
    context =  {'url_name': 'subscription',
                "price_list": prices['data'],
                'stripe_public_key': os.environ.get('STRIPE_APP_KEY'),
                "APP_URL": os.environ.get('FRONTEND'),
                "DOMAIN_URL": os.environ.get('DOMAIN_URL'),
                "esecretKey": os.environ.get('ENCRIPTION_SECRET_KEY')
                  }
    return render(request, "after-login/subscription.html", context)


@csrf_exempt
def get_stripe_transaction_history(request):
    user_id = request.POST.get('id')
    users = Users.objects.filter(pk=user_id)
    plan_type = None
    subscription_history = []
    if users.exists():
        subscription_record = Subscriptions.objects.filter(user=users.first(), is_delete=False)
        if subscription_record.exists():
            try:
                web_purchase_records = subscription_record.exclude(stripe_customer_id__isnull=True).exclude(stripe_customer_id__exact='')
                ios_purchase_records = subscription_record.exclude(receipt__isnull=True)    
                if web_purchase_records.exists():
                    first_subscription_record = web_purchase_records.latest('created_date')
                    customer = stripe.Customer.retrieve(first_subscription_record.stripe_customer_id)
                    subscription_history = stripe.Invoice.list(customer=customer)
                    plan_type = subscription_history['data'][0]['lines']['data'][0]['plan']['interval']
                if ios_purchase_records.exists():
                    first_subscription_record = ios_purchase_records.latest('created_date')
                    # subscription_history = list(SubscriptionHistory.objects.filter(user_id=user_id).values())
                    plan_type = 'month' if first_subscription_record.plan_type == None else first_subscription_record.plan_type
                context = { 'subscription_record': list(subscription_record.values()), 'message': 'user_found', "APP_URL": os.environ.get('FRONTEND'), "plan_type":plan_type, "free_trials": users.first().free_trials_available,
                           "stripe_subscription_history": subscription_history,
                            #  "app_purchase_history": subscription_history 
                             }
                return JsonResponse(context)
            except Exception as e:
                logger.error("Subscribtion in test mode so history not found!")
                f = open("experhealth_webapp.log", "a")
                # writing in the file
                f.write(str(e) + "\n")
                # closing the file
                f.close()
                context = {'subscription_history': [], 'subscription_record': [], 'message': 'user_found', "APP_URL": os.environ.get('FRONTEND'),
                           "stripe_subscription_history": [], "plan_type":plan_type, "free_trials": users.first().free_trials_available}
                return JsonResponse(context)
        else:
            context = {'subscription_history': [], 'stripe_subscription_history': [], 'subscription_record': [], 'message': 'user_found', "APP_URL": os.environ.get('FRONTEND'), "plan_type":plan_type, "free_trials": users.first().free_trials_available}
            return JsonResponse(context)

    else:
        logger.info("User not found in database for transaction history!")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")
        # closing the file
        f.close()
        context = {'subscription_history': None, 'subscription_record': None, 'message': 'user_not_found', "APP_URL": os.environ.get('FRONTEND'), "plan_type":plan_type, "free_trials": 0}
        return JsonResponse(context, safe=False)   


@csrf_exempt
def create_checkout_session(request):
    if request.method == 'POST':
        price_id = request.POST.get('price_id')
        userid = request.POST.get('id')
        user = Users.objects.get(pk=userid)
        plan_type = request.POST.get('plan_type')
        plan = request.POST.get('plan')
        discount_code = request.POST.get('coupon')
        subscription_record = Subscriptions.objects.filter(user = user, is_delete=False)
        if subscription_record.exists():
            customer_obj = stripe.Customer.retrieve(subscription_record[0].stripe_customer_id)
        else:
            customer_obj = stripe.Customer.create(name=user.username,
                            email=user.email)
        domain_url = os.environ.get('DOMAIN_URL')
        try:
            if plan_type == "year" and discount_code != None:
                    discount_obj = DiscountCodes.objects.get(discount_code__iexact=discount_code)
                    search_query = "active:'true' AND metadata['discount_code']:'{}' AND metadata['created_by']:'code' AND metadata['plan_type']: '{}'".format(discount_code, plan.lower())
                    subscription_price = stripe.Price.search(query=search_query, limit=10)
                    # Checkout like this only if discount code is passed otherwise normal subscription workflow
                    checkout_session = stripe.checkout.Session.create(
                        customer=customer_obj,
                        client_reference_id=user.username,
                        success_url=domain_url + 'success?session_id={CHECKOUT_SESSION_ID}',
                        cancel_url=domain_url + 'subscription',
                        payment_method_types=['card'],
                        mode='subscription',
                        metadata={'plan': request.POST.get('plan'), 'email': user.email, 'id': user.pk, 'subscription_type': request.POST.get('plan_type'),
                                "price_id": price_id, "with_discount": True, "discount_code": discount_obj.discount_code,
                                "discount_percentage": discount_obj.discount_percentage},
                        line_items=[
                            {
                                "price": subscription_price['data'][0]['id'],
                                "quantity": 1
                            },
                        ],
                        custom_text={
                            "terms_of_service_acceptance": {
                                "message": "From next invoice you will be charged full amount for the subscription"
                            }
                        },
                        consent_collection={
                            "terms_of_service": "required"
                        }              
                    )
            else:
                checkout_session = stripe.checkout.Session.create(
                customer=customer_obj,
                client_reference_id=user.username,
                success_url=domain_url + 'success?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=domain_url + 'subscription',
                payment_method_types=['card'],
                mode='subscription',
                metadata={'plan': request.POST.get('plan'), 'email': user.email, 'id': user.pk, 'subscription_type': request.POST.get('plan_type'),
                          "price_id": price_id, "with_discount": False},
                line_items=[
                    {
                        'price': price_id,
                        'quantity': 1,
                    }
                ])

            return JsonResponse({'sessionId': checkout_session['id']})
        except Exception as e:
            logger.error("Error while creating checkout session: ")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close()
            return JsonResponse({'error': str(e)})
        

def session_success(request):
    try: 
        session_id = request.GET.get('session_id')
        session_obj = stripe.checkout.Session.retrieve(session_id, expand=['total_details.breakdown', 'subscription'])
        user = Users.objects.get(email = session_obj.metadata.email, id=session_obj.metadata.id)
        active = 1 if session_obj['status'] == "complete" else 0
        payment_methods = stripe.Customer.list_payment_methods(customer=session_obj.customer, type='card')
        # payment_method = payment_methods.data[0]
        discount_code = None
        discount_percent = None
        subscription_end_date = make_aware(datetime.now())
        if session_obj.metadata.subscription_type == "month":
            subscription_end_date = make_aware(datetime.now() + timedelta(days=30))
        elif session_obj.metadata.subscription_type == "year":
            subscription_end_date = make_aware(datetime.now() + timedelta(days=365))
        if eval(str(session_obj.metadata.get("with_discount")).capitalize()):
            subscriptions = stripe.Subscription.list(customer=session_obj.customer)
            response = stripe.Subscription.modify(
                                        subscriptions['data'][0]['id'],
                                        items=[{"id": subscriptions['data'][0]['items']['data'][0]['id'], "price": session_obj['metadata']['price_id']}],
                                        proration_behavior='none',
                                        metadata={"plan": session_obj['metadata']['plan']},
                                        billing_cycle_anchor="unchanged"
                                        )
            logger.info("Subscrption created with discount")
            discount_code = session_obj['metadata']['discount_code']
            discount_percent = session_obj['metadata']['discount_percentage']
        subscription_obj = None
        if Subscriptions.objects.filter(user=user, stripe_customer_id__isnull=False, is_delete=False).exists():
            subscription_obj = Subscriptions.objects.get(user=user, stripe_customer_id__isnull=False, is_delete=False)
            subscription_obj.is_active = 1
            subscription_obj.plan = session_obj['metadata']['plan']
            subscription_obj.remarks = "Resumed the subscription"
            subscription_obj.modified_date = make_aware(datetime.now())
            subscription_obj.plan_price = session_obj['amount_total']/100
            subscription_obj.start_date = make_aware(datetime.now())
            subscription_obj.end_date = subscription_end_date
            subscription_obj.discount_code = discount_code
            subscription_obj.discount_percentage = discount_percent
            subscription_obj.plan_type = session_obj.metadata.subscription_type
            subscription_obj.save()
        else:
            subscription_obj = Subscriptions.objects.create(user=user, created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()), stripe_customer_id=session_obj['customer'], is_active=active, is_delete=0, is_testdata=1, plan=session_obj['metadata']['plan'], remarks="User is subscribed",
                                                            plan_price=session_obj['amount_total']/100, start_date = make_aware(datetime.now()), end_date = subscription_end_date,
                                                            discount_code = discount_code, discount_percentage = discount_percent, plan_type=session_obj.metadata.subscription_type)
            
            SubscriptionHistory.objects.create(subscription = subscription_obj, user = subscription_obj.user, amount = session_obj['amount_total']/100, remarks="Subscription created", created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()),
                                            plan_type=session_obj.metadata.subscription_type, plan=session_obj['metadata']['plan'], is_testdata=1, start_date=make_aware(datetime.now()), end_date=subscription_end_date, is_active=1)
    except Exception as e:
        logger.error("Error while saving subscription info to database: %s")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        pass
    for item in payment_methods.data:
        try:
            UserCards.objects.create(subscription=subscription_obj,
                                    card_brand = item['card']['brand'],
                                    expire_month = item['card']['exp_month'],
                                    expire_year = item['card']['exp_year'],
                                    last_4_digit = item['card']['last4'],
                                    name_on_card = item['billing_details']['name'])
        except Exception as e:
            logger.error("Error while creating card object: %s")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close()
            pass
    return render(request, 'subscription_page/success.html', {"APP_URL": os.environ.get('FRONTEND'), "esecretKey": os.environ.get('ENCRIPTION_SECRET_KEY')}) 

def session_cancel(request):
    return render(request, 'subscription_page/cancel.html', {"APP_URL": os.environ.get('FRONTEND'), "esecretKey": os.environ.get('ENCRIPTION_SECRET_KEY')}) 


@csrf_exempt
def delete_subscription(request):
    user = Users.objects.get(pk=request.POST.get('id'))
    customer = Subscriptions.objects.get(user=user, stripe_customer_id__isnull=False)
    if customer.plan == 'ENTERPRISE':
        response = {'status': 'canceled'}
    else:
        stripe_subscriptions = stripe.Subscription.list(customer=customer.stripe_customer_id, price=request.POST.get('price_id'))
        response = stripe.Subscription.cancel(stripe_subscriptions['data'][0]['id'])
    if response['status'] == 'canceled':
        customer.is_active = 0
        customer.modified_date = make_aware(datetime.now())
        customer.remarks = "Subscription cancelled"
        customer.save()
        SubscriptionHistory.objects.create(subscription = customer, user = user, amount = 0, created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()),
                                           plan_type="", remarks="Subscription canceled",  is_testdata=1, start_date=make_aware(datetime.now()), end_date=make_aware(datetime.now()), is_active=0)
        context = {"message": "SUCCESS"}
    else:
        logger.error("Error while deleting subscription.")
        context = {"message": "ERROR"}
    return JsonResponse(context)

@csrf_exempt
def upgrade_subscription(request):
    try:
        user = Users.objects.get(pk=request.POST.get('id'))
        subscription_obj = Subscriptions.objects.get(user = user, stripe_customer_id__isnull=False)
        subscriptions = stripe.Subscription.list(customer=f'{subscription_obj.stripe_customer_id}')
        respponse = stripe.Subscription.modify(
                                    f"{subscriptions['data'][0]['id']}",
                                    items=[{"id": f"{subscriptions['data'][0]['items']['data'][0]['id']}", "price": f"{request.POST.get('price_id')}"}],
                                    proration_behavior='always_invoice',
                                    metadata={"plan": request.POST.get('plan')},
                                    )
        SubscriptionHistory.objects.create(subscription = subscription_obj, user = subscription_obj.user, amount = respponse['items']['data'][0]['unit_amount']/100, remarks="Subscription modified", created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()),
                                           plan_type=respponse.metadata.subscription_type, is_testdata=1, start_date=make_aware(datetime.now()), end_date=subscription_obj.end_date, is_active=1)
        subscription_obj.plan = respponse['metadata']['plan']
        subscription_obj.plan_price = respponse['plan']['amount']/100
        subscription_obj.save()
        context = {"message": "SUCCESS"}
    except Exception as e:
        logger.error("Error while updating subscription details")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        context = {"message": "ERROR"}
    return JsonResponse(context)
    
@csrf_exempt
def customer_portal(request):
    # For demonstration purposes, we're using the Checkout session to retrieve the customer ID.
    # Typically this is stored alongside the authenticated user in your database.

    checkout_session_id = request.POST.get('session_id')
    checkout_session = stripe.checkout.Session.retrieve(checkout_session_id)

    # This is the URL to which the customer will be redirected after they are
    # done managing their billing with the portal.
    # return_url = "http://localhost:8000/subscription"
    return_url = os.environ.get("DOMAIN_URL") + "subscription"

    portalSession = stripe.billing_portal.Session.create(
        customer=checkout_session.customer,
        return_url=return_url,
    )
    return JsonResponse({"url": portalSession.url})


def call_subscription_page(request):
    return render(request, 'after-login/load_subscription_page.html', {"APP_URL": os.environ.get('FRONTEND'), "esecretKey": os.environ.get('ENCRIPTION_SECRET_KEY')})


@csrf_exempt
def payment_webhook(request):
    endpoint_secret = os.environ.get('WEBHOOK_SECRET')
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    event = None
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError as e:
        # Invalid payload
        logger.error("Webhook error for invalid payload")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error("Webhook error for invalid signature")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
    print("webhook called: event type: ", event['type'])
    if event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        try:
            if invoice['lines']["data"][0]["description"] == "ENTERPRISE":
                return HttpResponse(status=200)
        except Exception as e:
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close() 
            pass
        context = {
            'email_title': "New Subscription Created" if invoice['billing_reason'] == "subscription_create" else "Subscription renewal Successfull",
            'message_data': f"Payment of ${invoice['total']/100} received in stripe account for plan: {invoice['lines']['data'][0]['description']}",
            'APP_URL': os.environ.get('FRONTEND')
        }
        subject = "New Subscription Created" if invoice['billing_reason'] == "subscription_create" else "Subscription renewal Successfull"
        to =  TO_EMAIL
        template_name = "email-template/admin_email.html"
        convert_to_html_content =  render_to_string(
                                        template_name=template_name,
                                        context=context)
        try:
            msg = EmailMultiAlternatives(
            subject,
            convert_to_html_content,
            from_email=settings.EMAIL_HOST_USER,
            to=[to]
            )
            msg.mixed_subtype = 'related'
            msg.attach_alternative(convert_to_html_content, "text/html")
            img_dir = 'static'
            image = 'Logo.png'
            file_path = os.path.join(img_dir, 'img', image)
            img=None
            with open(file_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<{name}>'.format(name=image))
                img.add_header('Content-Disposition', 'inline', filename=image)
            msg.attach(img)
            msg.send()
            logger.info("Email sent to admin")
        except Exception as e:
            logger.error("Error while sending email")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close() 
            pass
        try:
            subscription_obj = Subscriptions.objects.filter(stripe_customer_id = invoice['customer'], is_delete=False)
            subscription_obj.update(is_active=1, modified_date=make_aware(datetime.now()), end_date = make_aware(datetime.now()) + timedelta(days=30),
                                                                                        remarks=subject)
            if subscription_obj.exists():
                SubscriptionHistory.objects.create(subscription = subscription_obj.latest(), user = subscription_obj.latest().user, amount= invoice['total']/100, remarks="Subscription Renewal", created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()), plan_type=subscription_obj.latest().plan_type,
                                               is_testdata=1, start_date=make_aware(datetime.now()), end_date=subscription_obj.latest().end_date, is_active=1)
        except Exception as e:
            logger.error("Error while update subscription and history table")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close() 
            pass
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        context = {
            'email_title': "Subscription renewal Failed",
            'message_data': f"Payment of ${invoice['total']/100} failed for plan: {invoice['lines']['data'][0]['description']}"
        }
        subject =  "Subscription Failed" if invoice['billing_reason'] == "subscription_create" else "Subscription renewal Failed"
        to = TO_EMAIL
        template_name = "email-template/admin_email.html"
        convert_to_html_content =  render_to_string(
                                        template_name=template_name,
                                        context=context
                                    )
        try:
            msg = EmailMultiAlternatives(
            subject,
            convert_to_html_content,
            from_email=settings.EMAIL_HOST_USER,
            to=[to]
            )
            msg.mixed_subtype = 'related'
            msg.attach_alternative(convert_to_html_content, "text/html")
            img_dir = 'static'
            image = 'Logo.png'
            file_path = os.path.join(img_dir, 'img', image)
            img=None
            with open(file_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<{name}>'.format(name=image))
                img.add_header('Content-Disposition', 'inline', filename=image)
            msg.attach(img)
            msg.send()
            logger.info("Email sent to admin")
        except Exception as e:
            logger.error("Error while sending email")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close()
        try:
            subscription_obj = Subscriptions.objects.filter(stripe_customer_id = invoice['customer'], is_delete=False)
            subscription_obj.update(is_active=0, modified_date=make_aware(datetime.now()), remarks="Payment failed for subscription", end_date = make_aware(datetime.now()))
            if subscription_obj.exists():
                SubscriptionHistory.objects.create(subscription = subscription_obj.latest(), user = subscription_obj.latest().user, amount= 0, remarks="Subscription renewal failed due to payment failour", created_date=make_aware(datetime.now()), modified_date=make_aware(datetime.now()), plan_type=subscription_obj.latest().plan_type,
                                               is_testdata=1, start_date=make_aware(datetime.now()), end_date=subscription_obj.latest().end_date, is_active=1)
        except Exception as e:
            logger.error("Error while update subscription and history table")
            f = open("experhealth_webapp.log", "a")
            # writing in the file
            f.write(str(e) + "\n")         
            # closing the file
            f.close() 
            pass
    elif event['type'] == 'checkout.session.completed':
        # for payment via link
        session_obj = event['data']['object']
        subscription_end_date = timezone.now() + timezone.timedelta(days=365)
        if session_obj['metadata']['plan'] == "ENTERPRISE":
            context = {
                'email_title': "New Subscription Created",
                'message_data': f"Payment of ${session_obj['amount_total']/100} received in stripe account for plan: {session_obj['metadata']['plan']}",
                'APP_URL': os.environ.get('FRONTEND')
            }
            subject = "New Subscription Created"
            to =  TO_EMAIL
            template_name = "email-template/admin_email.html"
            convert_to_html_content =  render_to_string(
                                            template_name=template_name,
                                            context=context)
            try:
                msg = EmailMultiAlternatives(
                subject,
                convert_to_html_content,
                from_email=settings.EMAIL_HOST_USER,
                to=[to]
                )
                msg.mixed_subtype = 'related'
                msg.attach_alternative(convert_to_html_content, "text/html")
                img_dir = 'static'
                image = 'Logo.png'
                file_path = os.path.join(img_dir, 'img', image)
                img=None
                with open(file_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<{name}>'.format(name=image))
                    img.add_header('Content-Disposition', 'inline', filename=image)
                msg.attach(img)
                msg.send()
                logger.info("Email sent to admin")
            except Exception as e:
                logger.error("Error while sending email")
                f = open("experhealth_webapp.log", "a")
                # writing in the file
                f.write(str(e) + "\n")         
                # closing the file
                f.close() 
                pass
                 
            org_user = Users.objects.get(pk=session_obj['metadata']['id'])
            if Subscriptions.objects.filter(id=session_obj['metadata']['subscription_id']).exists():
                subscription_obj = Subscriptions.objects.get(id=session_obj['metadata']['subscription_id'])
                subscription_obj.is_active = 1
                subscription_obj.plan = session_obj['metadata']['plan']
                subscription_obj.remarks = "Org Subscribed"
                subscription_obj.modified_date = timezone.now()
                subscription_obj.plan_price = session_obj['amount_total']/100
                subscription_obj.start_date = timezone.now()
                subscription_obj.end_date = subscription_end_date
                subscription_obj.discount_code = ""
                subscription_obj.discount_percentage = ""
                subscription_obj.plan_type = session_obj.metadata.subscription_type
                subscription_obj.payment_method = "Online"
                subscription_obj.stripe_customer_id = session_obj["customer"]
                subscription_obj.save()
                remark = f"Org Subscribed, {session_obj['customer']}"
                SubscriptionHistory.objects.create(subscription = subscription_obj, user = subscription_obj.user, amount = session_obj['amount_total']/100, remarks=remark, created_date=timezone.now(), modified_date=timezone.now(),
                                                plan_type=session_obj.metadata.subscription_type, plan=session_obj['metadata']['plan'], is_testdata=1, start_date=timezone.now(), end_date=subscription_end_date, is_active=1, is_delete=0)
            else:
                subscription_obj = Subscriptions.objects.create(user=org_user, created_date=timezone.now(), modified_date=timezone.now(), stripe_customer_id=session_obj['customer'], is_active=1, is_delete=0, is_testdata=1, plan=session_obj['metadata']['plan'], remarks="Organisation is subscribed",
                                                                plan_price=session_obj['amount_total']/100, start_date = timezone.now(), end_date = subscription_end_date,
                                                                discount_code = "", discount_percentage = "", plan_type=session_obj.metadata.subscription_type, payment_method="Online")
                remark = f"Org Subscribed, {session_obj['customer']}"
                SubscriptionHistory.objects.create(subscription = subscription_obj, user = subscription_obj.user, amount = session_obj['amount_total']/100, remarks=remark, created_date=timezone.now(), modified_date=timezone.now(),
                                                plan_type=session_obj.metadata.subscription_type, plan=session_obj['metadata']['plan'], is_testdata=1, start_date=timezone.now(), end_date=subscription_end_date, is_active=1, is_delete = 0)

    return HttpResponse(status=200)


def health(request):
    return JsonResponse({"status": 200, "message": "SUCCESS"})

@csrf_exempt
def upload_files_s3bucket(request):

    try:
        file_s3_paths = {}
        for key in request.FILES.keys():
            s3 = boto3.resource('s3')
            file = request.FILES[key]
            actual_name = file.name.split('.')[0]
            extension = file.name.split('.')[-1]
            new_name = actual_name + '_' + str(uuid.uuid4()) + '.' + extension
            file_key = key+"/"+new_name
            file_s3_paths[key] = file_key
            response = s3.Bucket(bucket_name).put_object(Key=file_key, Body=file)
        return JsonResponse({"status": "SUCCESS", "message": "File Uploaded successfully", "data": {"file_name": file_s3_paths}})
    except Exception as e:
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()        
        return JsonResponse({'status': "ERROR", "message": "File Upload Failed", "data": {"bucket_name": bucket_name}})
        

@csrf_exempt
def create_coupon(request, record_id):
    try:
        discount_obj = DiscountCodes.objects.get(id=record_id)
        prices = SubscriptionFees.objects.filter(is_delete=False, plan_type__icontains="year")
        for price in prices:
            validity_months = [int(i) for i in discount_obj.validity.split() if i.isdigit()][0]
            if "month" in discount_obj.validity.lower():
                total_discount_duration = validity_months
            if "year" in discount_obj.validity.lower():
                total_discount_duration = validity_months * 12
            original_price_per_month = (float(price.plan_price) / 12)
            if discount_obj.discount_percentage == None or discount_obj.discount_percentage == '':
                discount = float(discount_obj.discount_amount)
            else:
                if float(discount_obj.discount_percentage) <= 100 and validity_months < 12:
                    discount = (float(discount_obj.discount_percentage) / 100) * original_price_per_month
                else:
                    if validity_months > 12:
                        logger.info("Discount for more than a year, discount not created for second year")
                        return JsonResponse({"message": "Can not create coupon for more than 1 year validity", "status": "FAILURE"})
                    discount = (float(price.plan_price) * 100)
                    # total_after_discount = 0
            discounted_price_per_month = original_price_per_month - discount
            remaining_months = 12 - total_discount_duration
            total_after_discount = ((total_discount_duration * discounted_price_per_month) + (remaining_months * original_price_per_month)) * 100
               
               
            product = stripe.Price.retrieve(price.stripe_price_id)
            stripe_price_obj = stripe.Price.create(
                currency='usd',
                metadata= {
                    "price_id" : price.id,
                    "discount_code_id": discount_obj.id,
                    "discount_percent": discount_obj.discount_percentage,
                    "discount_amount": discount_obj.discount_amount,
                    "discount_code": discount_obj.discount_code,
                    "created_by": "code",
                    "price": price.plan_price,
                    "plan_type": price.plan_name,
                    "billing_period": "yearly",
                    "product": price.plan_name.upper()
                },
                product=product['product'],
                recurring={"interval": "year"},
                unit_amount= round(total_after_discount)
            )
            if discount_obj.stripe_price_list == "" or discount_obj.stripe_price_list == None:
                discount_obj.stripe_price_list = stripe_price_obj.id
            else:
                discount_obj.stripe_price_list = discount_obj.stripe_price_list + "," + stripe_price_obj.id
            discount_obj.save()
        return JsonResponse({"message": "Coupon created successfully", "status": "SUCCESS"})
    except Exception as e:
        logger.error("Error while creating coupon and promo code")
        print(e)
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        return JsonResponse({"message": "error", "status": "FAILURE"})



@csrf_exempt
def edit_coupon(request, record_id):
    try:
        discount_obj = DiscountCodes.objects.get(id=record_id)
        stripe_prices_list = discount_obj.stripe_price_list.split(',')
        delete_price = False
        create_new = True
        active_price = False
        stripe_price_obj = stripe.Price.retrieve(stripe_prices_list[0])
        if discount_obj.is_active == 0:
            delete_price = True
            create_new = False
        if discount_obj.is_active == 1 and not stripe_price_obj.active:
            active_price = True
        if discount_obj.is_delete == 1:
            delete_price = True
            create_new = False
        if not str(stripe_price_obj['metadata']['discount_percent']).lower() == str(discount_obj.discount_percentage).lower() and \
            not stripe_price_obj['metadata']['discount_code'].lower() == discount_obj.discount_code.lower():
            active_price = False
            delete_price = True

        if active_price:
            for price_id in stripe_prices_list:
                stripe.Price.modify(id=price_id,
                                    active=True  ,
                                    metadata={
                                        'deleted': False
                                    })
        elif delete_price:
            for price_id in stripe_prices_list:
                stripe.Price.modify(id=price_id,
                                    active=False  ,
                                    metadata={
                                        'deleted': True
                                    })

            if create_new:
                discount_obj.stripe_price_list = ""
                discount_obj.save()
                prices = SubscriptionFees.objects.filter(is_delete=False, plan_type__icontains="year")
                for index, price in enumerate(prices):
                    validity_months = [int(i) for i in discount_obj.validity.split() if i.isdigit()][0]
                    if "month" in discount_obj.validity.lower():
                        total_discount_duration = validity_months
                    if "year" in discount_obj.validity.lower():
                        total_discount_duration = validity_months * 12
                    original_price_per_month = (float(price.plan_price) / 12)
                    if discount_obj.discount_percentage == None or discount_obj.discount_percentage == '':
                        discount = float(discount_obj.discount_amount)
                    else:
                        if float(discount_obj.discount_percentage) <= 100 and validity_months < 12:
                            discount = (float(discount_obj.discount_percentage) / 100) * original_price_per_month
                        else:
                            if validity_months > 12:
                                logger.info("Discount for more than a year, discount not created for second year")
                                return JsonResponse({"message": "Can not create coupon for more than 1 year validity", "status": "FAILURE"})
                            discount = (float(price.plan_price) * 100)
                            # total_after_discount = 0
                    discounted_price_per_month = original_price_per_month - discount
                    remaining_months = 12 - total_discount_duration
                    total_after_discount = ((total_discount_duration * discounted_price_per_month) + (remaining_months * original_price_per_month)) * 100
                    
                    
                    product = stripe.Price.retrieve(price.stripe_price_id)
                    stripe_price_obj = stripe.Price.create(
                        currency='usd',
                        metadata= {
                            "price_id" : price.id,
                            "discount_code_id": discount_obj.id,
                            "discount_percent": discount_obj.discount_percentage,
                            "discount_amount": discount_obj.discount_amount,
                            "discount_code": discount_obj.discount_code,
                            "created_by": "code",
                            "price": price.plan_price,
                            "plan_type": price.plan_name,
                            "billing_period": "yearly",
                            "product": price.plan_name.upper()
                        },
                        product=product['product'],
                        recurring={"interval": "year"},
                        unit_amount= round(total_after_discount)
                    )
                    if discount_obj.stripe_price_list == "" or discount_obj.stripe_price_list == None:
                        discount_obj.stripe_price_list = stripe_price_obj.id
                    else:
                        discount_obj.stripe_price_list = discount_obj.stripe_price_list + "," + stripe_price_obj.id
                    discount_obj.save()
        return JsonResponse({"message": "Coupon updated successfully", "status": "SUCCESS"})
    except Exception as e:
        logger.error("Error while updating coupon and promo code")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        return JsonResponse({"message": "Error while updating coupon and promo code", "status": "FAILURE"})


@csrf_exempt
def edit_plan_price(request, record_id):
    try:
        # need to create new price and allocate each user to that new plan one by one then update price id in record object from database
        record_obj = SubscriptionFees.objects.get(pk=record_id)
        old_price = stripe.Price.modify(record_obj.stripe_price_id, active=False)
        subscriptions_list = Subscriptions.objects.filter(plan__icontains=record_obj.plan_name)
        new_price_record = stripe.Price.create(product=old_price['product'],
                                unit_amount=round(float(record_obj.plan_price) * 100),
                                recurring=old_price['recurring'],
                                metadata= old_price['metadata'],
                                currency=old_price['currency'])
        # Changing price for future payments in older subscriptions
        for subscrption_record in subscriptions_list:
            subscriptions = stripe.Subscription.list(customer=f'{subscrption_record.stripe_customer_id}')
            for subsription_rec in subscriptions['data']:
            
                response = stripe.Subscription.modify(
                                    subscriptions['data'][0]['id'],
                                    items=[{"id": subsription_rec['items']['data'][0]['id'], "price": new_price_record['id']}],
                                    proration_behavior='none',
                                    billing_cycle_anchor="unchanged",
                                    )
        
        record_obj.stripe_price_id = new_price_record['id']
        record_obj.save()
        return JsonResponse({"message": "Price updated successfully", "status": "SUCCESS"})

    except Exception as e:
        logger.error("error while updating price")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        return JsonResponse({"message": "error", "status": "FAILURE"})


@csrf_exempt
def check_coupon_validity(request):
    code = request.POST.get("code")
    try:
        if code is not None:
            codes = DiscountCodes.objects.filter(discount_code__iexact=code, is_active=1, is_delete=0)
            if codes.exists():
                if codes.first().unit == None:
                    return JsonResponse({"message":"Valid", "status": "SUCCESS"})
                elif Subscriptions.objects.filter(discount_code__iexact=code).count() < codes.first().unit:
                    return JsonResponse({"message":"Valid", "status": "SUCCESS"})
                else:
                    return JsonResponse({"message":"Invalid", "status": "SUCCESS"})
            else:
                return JsonResponse({"message":"Invalid", "status": "SUCCESS"})
        else:
            return JsonResponse({"message":"No code passed"})
    except Exception as e:
        logger.error("Error while validating coupon")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")         
        # closing the file
        f.close()
        return JsonResponse({"message": "error", "status": "FAILURE"}, status=400)



def generate_payment_link(request):
    minimum_unit = request.GET.get('unit')
    unit_price = request.GET.get('unit_price')
    email = request.GET.get('email')
    user_id = request.GET.get('user_id')
    subscription_id = request.GET.get('subscription_id')
    # search in prices for matching price
    price_query = "metadata['lookup_key']:'ENTERPRISE_CODE' AND metadata['price']:'{}'".format(unit_price)
    prices = stripe.Price.search(query=price_query)
    if len(prices['data']) == 0:
        product = stripe.Product.search(query="name~'ENTERPRISE'")
        # create new price     
        price = stripe.Price.create(
            currency='usd',
            unit_amount=round(float(unit_price) * 100),
            product=product['data'][0]['id'],
            metadata= {
                "price": unit_price,
                "billing_period": "Yearly",
                "created_by": "code",
                "plan_type": "ENTERPRISE",
                "lookup_key": "ENTERPRISE_CODE",
            }
        )
        plan_price = price
    else:
        plan_price = prices['data'][0]
    try:
        response = stripe.PaymentLink.create(
            line_items=[
                {
                "price": plan_price['id'],
                "quantity": int(minimum_unit),
                "adjustable_quantity": {"enabled": True, "minimum": int(minimum_unit), "maximum": int(minimum_unit) + 10 },
                },
            ],
            metadata= {'plan': "ENTERPRISE", 'email': email, 'id': user_id, 'subscription_type': "Yearly",
                          "price_id": plan_price['id'], "with_discount": False, "subscription_id": subscription_id
                },       
            restrictions={
                    "completed_sessions":{
                        "limit": 1
                    }
            },
              invoice_creation={"enabled": True},
              customer_creation="always"
        )
        return JsonResponse({"url": response['url'], "status": "SUCCESS"})
    except Exception as e:
        logger.error("Error while generating payment link")
        f = open("experhealth_webapp.log", "a")
        # writing in the file
        f.write(str(e) + "\n")
        # closing the file
        f.close()

