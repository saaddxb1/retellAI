from django.db import models
from django.db.models.signals import post_migrate
from django.dispatch import receiver

class Patient(models.Model):
    patientName = models.CharField(max_length=100)
    patientPhone = models.CharField(max_length=20, unique=True)
    dateOfBirth = models.DateField(null=True, blank=True)
    email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return f"{self.patientName} ({self.patientPhone})"

class Doctor(models.Model):
    name = models.CharField(max_length=100)
    specialty = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, null=True, blank=True)
    language = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.specialty})"

class DoctorWorkingHours(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="workingHours")
    dayOfWeek = models.IntegerField()
    startTime = models.TimeField()
    endTime = models.TimeField()

    def __str__(self):
        return f"{self.doctor.name} day {self.dayOfWeek} {self.startTime}-{self.endTime}"

class Appointment(models.Model):
    STATUS_CHOICES = [
        ("BOOKED", "Booked"),
        ("CANCELLED", "Cancelled"),
        ("RESCHEDULED", "Rescheduled"),
        ("COMPLETED", "Completed"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="appointments")
    patientName = models.CharField(max_length=100)
    patientPhone = models.CharField(max_length=20)
    startTime = models.DateTimeField()
    endTime = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="BOOKED")
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patientName} with {self.doctor.name} @ {self.startTime}"

class AuditLog(models.Model):
    actionType = models.CharField(max_length=50)
    appointment = models.ForeignKey(Appointment, null=True, blank=True, on_delete=models.SET_NULL)
    patient = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.SET_NULL)
    doctor = models.ForeignKey(Doctor, null=True, blank=True, on_delete=models.SET_NULL)
    details = models.TextField(null=True, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.actionType}] {self.createdAt}"

# Create a separate function for dummy data
def create_dummy_data():
    """Create demo doctors, patients, and working hours if the Doctor table is empty."""
    if Doctor.objects.exists():
        return

    import datetime
    from django.utils import timezone

    # Create some doctors
    drSarah = Doctor.objects.create(
        name="Dr Sarah",
        specialty="General",
        gender="Female",
        language="English, Arabic",
    )
    drAli = Doctor.objects.create(
        name="Dr Ali",
        specialty="Cardiology",
        gender="Male",
        language="English",
    )
    drOmar = Doctor.objects.create(
        name="Dr Omar",
        specialty="General",
        gender="Male",
        language="English, Urdu",
    )

    # Simple working hours: Mon–Fri 09:00–17:00 for each doctor
    for doctor in [drSarah, drAli, drOmar]:
        for day in range(0, 5):  # 0..4 = Mon..Fri
            DoctorWorkingHours.objects.create(
                doctor=doctor,
                dayOfWeek=day,
                startTime=datetime.time(hour=9, minute=0),
                endTime=datetime.time(hour=17, minute=0),
            )

    # Create a couple of demo patients
    patient1 = Patient.objects.create(
        patientName="Ahmed Ali",
        patientPhone="+971500000001",
        email="ahmed@example.com",
    )
    patient2 = Patient.objects.create(
        patientName="Fatima Khan",
        patientPhone="+971500000002",
        email="fatima@example.com",
    )

    # Demo appointment
    now = timezone.now()
    later = now + datetime.timedelta(minutes=30)
    Appointment.objects.create(
        patient=patient1,
        doctor=drSarah,
        patientName=patient1.patientName,
        patientPhone=patient1.patientPhone,
        startTime=now,
        endTime=later,
        status="BOOKED",
    )
    print("Dummy data created successfully!")

# Manual function to call when needed
def init_database():
    create_dummy_data()