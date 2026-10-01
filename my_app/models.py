from django.db import models

# Create your models here.

class AdminUsers(models.Model):
    email = models.CharField(max_length=50)
    username = models.CharField(max_length=50)
    password = models.CharField(max_length=255, blank=True, null=True)
    forgot_pass_identity = models.TextField(blank=True, null=True)
    profile_image = models.CharField(max_length=255, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    phone_number = models.CharField(max_length=100, blank=True, null=True)
    guid = models.CharField(max_length=100)
    is_email_verified = models.IntegerField()
    is_admin = models.IntegerField()
    is_active = models.IntegerField()
    is_testdata = models.IntegerField()
    is_deleted = models.IntegerField()
    created_date = models.DateTimeField()
    modified_date = models.DateTimeField()
    failed_attempts = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'admin_users'


class Appointments(models.Model):
    patient = models.ForeignKey('Patients', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    health_system_appointment_id = models.CharField(max_length=45, blank=True, null=True)
    department_id = models.CharField(max_length=45, blank=True, null=True)
    provider_id = models.CharField(max_length=45, blank=True, null=True)
    encounter_id = models.CharField(max_length=45, blank=True, null=True)
    appointment_type = models.CharField(max_length=45, blank=True, null=True)
    is_checked_in = models.IntegerField(blank=True, null=True)
    appointment_date = models.DateTimeField(blank=True, null=True)
    is_delete = models.IntegerField(blank=True, null=True)
    is_testdata = models.IntegerField(blank=True, null=True)
    created_date = models.DateTimeField(blank=True, null=True)
    modified_date = models.DateTimeField(blank=True, null=True)
    meeting = models.ForeignKey('MeetingRecording', models.DO_NOTHING, blank=True, null=True)
    uploaded_to_health_system = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'appointments'