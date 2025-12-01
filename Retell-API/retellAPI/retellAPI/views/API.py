import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from django.http import JsonResponse, HttpResponseNotAllowed
from django.views import View
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from retellAPI.models import Patient, Doctor, DoctorWorkingHours, Appointment, AuditLog

# -----------------------------
# Helper functions
# -----------------------------

def parseIsoDatetime(dtStr: str) -> datetime:
    """Parse an ISO datetime string like '2025-12-01T10:30:00'."""
    return datetime.fromisoformat(dtStr)

def doctorHasConflict(
    doctor: Doctor,
    startTime: datetime,
    endTime: datetime,
    ignoreAppointmentId: Optional[int] = None,
) -> bool:
    """Check if doctor already has a booked appointment overlapping with [startTime, endTime)."""
    qs = Appointment.objects.filter(
        doctor=doctor,
        status="BOOKED",
        startTime__lt=endTime,
        endTime__gt=startTime,
    )
    if ignoreAppointmentId is not None:
        qs = qs.exclude(id=ignoreAppointmentId)

    return qs.exists()

def buildFreeSlots(
    dayStart: datetime,
    dayEnd: datetime,
    busyIntervals: List[Tuple[datetime, datetime]],
    durationMinutes: int,
) -> List[dict]:
    """Given a working window and busy intervals, compute free slots of given duration."""
    freeSlots = []
    current = dayStart

    for busyStart, busyEnd in busyIntervals:
        if busyStart > current:
            gap = (busStart - current).total_seconds() / 60.0
            if gap >= durationMinutes:
                slotEnd = current + timedelta(minutes=durationMinutes)
                freeSlots.append({
                    "startTime": current.isoformat(),
                    "endTime": slotEnd.isoformat()
                })
        if busyEnd > current:
            current = busyEnd

    if dayEnd > current:
        gap = (dayEnd - current).total_seconds() / 60.0
        if gap >= durationMinutes:
            slotEnd = current + timedelta(minutes=durationMinutes)
            freeSlots.append({
                "startTime": current.isoformat(),
                "endTime": slotEnd.isoformat()
            })

    return freeSlots

def getOrCreatePatient(patientName: str, patientPhone: Optional[str]) -> Patient:
    """Simple helper: look up patient by phone, else create new."""
    if not patientPhone:
        return Patient.objects.create(patientName=patientName, patientPhone=f"UNKNOWN-{patientName}")

    patient, created = Patient.objects.get_or_create(
        patientPhone=patientPhone,
        defaults={"patientName": patientName},
    )
    if not created and patient.patientName != patientName:
        patient.patientName = patientName
        patient.save(update_fields=["patientName"])
    return patient

def pickDoctor(doctorName: Optional[str], specialty: Optional[str]) -> Optional[Doctor]:
    """Pick doctor by name or specialty."""
    if doctorName:
        if specialty:
            doctorQs = Doctor.objects.filter(name=doctorName, specialty=specialty)
        else:
            doctorQs = Doctor.objects.filter(name=doctorName)
        doctor = doctorQs.first()
        if doctor:
            return doctor

    if specialty:
        return Doctor.objects.filter(specialty=specialty).first()

    return None

def getWorkingWindowForDoctor(doctor: Doctor, dateObj) -> Optional[List[Tuple[datetime, datetime]]]:
    """Get working intervals (start, end) for a doctor on a given date based on DoctorWorkingHours."""
    weekday = dateObj.weekday()  # 0=Mon..6=Sun
    rows = DoctorWorkingHours.objects.filter(doctor=doctor, dayOfWeek=weekday)
    if not rows.exists():
        return None

    intervals = []
    for row in rows:
        dayStart = datetime.combine(dateObj, row.startTime)
        dayEnd = datetime.combine(dateObj, row.endTime)
        intervals.append((dayStart, dayEnd))
    return intervals

# -----------------------------
# Core logic functions
# -----------------------------

def bookAppointmentLogic(args: dict) -> dict:
    """Book an appointment based on arguments coming from Retell."""
    patientName = args.get("patientName")
    patientPhone = args.get("patientPhone")
    doctorName = args.get("doctorName")
    specialty = args.get("specialty")
    startTimeStr = args.get("startTime")
    durationMinutes = args.get("durationMinutes", 30)

    if not patientName or not startTimeStr:
        return {
            "success": False,
            "error": "Missing required fields: patientName and startTime.",
        }

    try:
        startTime = parseIsoDatetime(startTimeStr)
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid datetime format for startTime: {startTimeStr}",
        }

    try:
        durationMinutes = int(durationMinutes)
    except (TypeError, ValueError):
        durationMinutes = 30

    endTime = startTime + timedelta(minutes=durationMinutes)

    doctor = pickDoctor(doctorName, specialty)
    if not doctor:
        return {
            "success": False,
            "error": f"No doctor found for doctorName='{doctorName}' and specialty='{specialty}'.",
        }

    # Working hours check
    workingIntervals = getWorkingWindowForDoctor(doctor, startTime.date())
    if not workingIntervals:
        return {
            "success": False,
            "error": "Doctor is not working on this day.",
        }

    insideWorkingTime = False
    for dayStart, dayEnd in workingIntervals:
        if startTime >= dayStart and endTime <= dayEnd:
            insideWorkingTime = True
            break
    if not insideWorkingTime:
        return {
            "success": False,
            "error": "Requested time is outside doctor's working hours.",
        }

    # Conflict check
    if doctorHasConflict(doctor, startTime, endTime):
        return {
            "success": False,
            "error": "Requested time slot is not available for this doctor.",
        }

    patient = getOrCreatePatient(patientName, patientPhone)

    with transaction.atomic():
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            patientName=patient.patientName,
            patientPhone=patient.patientPhone,
            startTime=startTime,
            endTime=endTime,
            status="BOOKED",
        )
        AuditLog.objects.create(
            actionType="BOOK",
            appointment=appointment,
            patient=patient,
            doctor=doctor,
            details=f"Booked by voice agent at {datetime.now().isoformat()}",
        )

    return {
        "success": True,
        "message": "Appointment booked successfully.",
        "appointmentId": appointment.id,
        "patientId": patient.id,
        "doctorId": doctor.id,
        "doctorName": doctor.name,
        "specialty": doctor.specialty,
        "startTime": appointment.startTime.isoformat(),
        "endTime": appointment.endTime.isoformat(),
    }

def cancelAppointmentLogic(args: dict) -> dict:
    """Cancel an appointment by ID."""
    appointmentId = args.get("appointmentId")
    if not appointmentId:
        return {
            "success": False,
            "error": "appointmentId is required.",
        }

    try:
        appointment = Appointment.objects.get(id=appointmentId)
    except Appointment.DoesNotExist:
        return {
            "success": False,
            "error": "Appointment not found.",
        }

    if appointment.status == "CANCELLED":
        return {
            "success": True,
            "message": "Appointment already cancelled.",
            "appointmentId": appointment.id,
        }

    appointment.status = "CANCELLED"
    appointment.save(update_fields=["status", "updatedAt"])

    AuditLog.objects.create(
        actionType="CANCEL",
        appointment=appointment,
        patient=appointment.patient,
        doctor=appointment.doctor,
        details=f"Cancelled by voice agent at {datetime.now().isoformat()}",
    )

    return {
        "success": True,
        "message": "Appointment cancelled.",
        "appointmentId": appointment.id,
    }

def rescheduleAppointmentLogic(args: dict) -> dict:
    """Reschedule an existing appointment to a new time."""
    appointmentId = args.get("appointmentId")
    newStartStr = args.get("newStartTime")
    durationMinutes = args.get("durationMinutes", 30)

    if not appointmentId or not newStartStr:
        return {
            "success": False,
            "error": "appointmentId and newStartTime are required.",
        }

    try:
        appointment = Appointment.objects.get(id=appointmentId)
    except Appointment.DoesNotExist:
        return {
            "success": False,
            "error": "Appointment not found.",
        }

    try:
        newStart = parseIsoDatetime(newStartStr)
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid datetime format for newStartTime: {newStartStr}",
        }

    try:
        durationMinutes = int(durationMinutes)
    except (TypeError, ValueError):
        durationMinutes = 30

    newEnd = newStart + timedelta(minutes=durationMinutes)

    if appointment.status == "CANCELLED":
        return {
            "success": False,
            "error": "Cannot reschedule a cancelled appointment.",
        }

    doctor = appointment.doctor

    # Working hours check
    workingIntervals = getWorkingWindowForDoctor(doctor, newStart.date())
    if not workingIntervals:
        return {
            "success": False,
            "error": "Doctor is not working on this day.",
        }

    insideWorkingTime = False
    for dayStart, dayEnd in workingIntervals:
        if newStart >= dayStart and newEnd <= dayEnd:
            insideWorkingTime = True
            break
    if not insideWorkingTime:
        return {
            "success": False,
            "error": "Requested new time is outside doctor's working hours.",
        }

    if doctorHasConflict(doctor, newStart, newEnd, ignoreAppointmentId=appointment.id):
        return {
            "success": False,
            "error": "Requested new time slot is not available for this doctor.",
        }

    appointment.startTime = newStart
    appointment.endTime = newEnd
    appointment.status = "BOOKED"
    appointment.save(update_fields=["startTime", "endTime", "status", "updatedAt"])

    AuditLog.objects.create(
        actionType="RESCHEDULE",
        appointment=appointment,
        patient=appointment.patient,
        doctor=doctor,
        details=f"Rescheduled by voice agent at {datetime.now().isoformat()}",
    )

    return {
        "success": True,
        "message": "Appointment rescheduled.",
        "appointmentId": appointment.id,
        "newStartTime": appointment.startTime.isoformat(),
        "newEndTime": appointment.endTime.isoformat(),
        "doctorId": doctor.id,
        "doctorName": doctor.name,
    }

def getAvailableSlotsLogic(args: dict) -> dict:
    """Return free slots for a doctor on a given date."""
    doctorName = args.get("doctorName")
    specialty = args.get("specialty")
    dateStr = args.get("date")
    durationMinutes = args.get("durationMinutes", 30)

    if not dateStr:
        return {
            "success": False,
            "error": "date is required (YYYY-MM-DD).",
        }

    try:
        dateObj = datetime.fromisoformat(dateStr).date()
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid date format (expected YYYY-MM-DD): {dateStr}",
        }

    try:
        durationMinutes = int(durationMinutes)
    except (TypeError, ValueError):
        durationMinutes = 30

    doctor = pickDoctor(doctorName, specialty)
    if not doctor:
        return {
            "success": False,
            "error": f"No doctor found for doctorName='{doctorName}' and specialty='{specialty}'.",
        }

    workingIntervals = getWorkingWindowForDoctor(doctor, dateObj)
    if not workingIntervals:
        return {
            "success": False,
            "error": "Doctor is not working on this day.",
        }

    busyAppointments = Appointment.objects.filter(
        doctor=doctor,
        status="BOOKED",
        startTime__date=dateObj,
    ).order_by("startTime")
    busyIntervals = [(a.startTime, a.endTime) for a in busyAppointments]

    slots = []
    for dayStart, dayEnd in workingIntervals:
        slots.extend(buildFreeSlots(dayStart, dayEnd, busyIntervals, durationMinutes))

    AuditLog.objects.create(
        actionType="GET_SLOTS",
        doctor=doctor,
        details=f"Checked available slots for {dateObj.isoformat()}",
    )

    return {
        "success": True,
        "doctorId": doctor.id,
        "doctorName": doctor.name,
        "specialty": doctor.specialty,
        "date": dateObj.isoformat(),
        "durationMinutes": durationMinutes,
        "slots": slots,
    }

# -----------------------------
# Main API View for Retell
# -----------------------------

@method_decorator(csrf_exempt, name='dispatch')
class API(View):
    """
    Single endpoint Retell will call.
    Expects JSON:
    {
      "function": "bookAppointment" | "cancelAppointment" | "rescheduleAppointment" | "getAvailableSlots",
      "arguments": { ... }
    }
    """
    def post(self, request, *args, **kwargs):
        """Handle API logic based on the function name."""
        body = request.body.decode("utf-8")
        try:
            data = json.loads(body)
        except Exception:
            return JsonResponse(
                {"success": False, "error": "Invalid JSON body."},
                status=400,
            )

        functionName = data.get("function")
        arguments = data.get("arguments", {}) or {}

        if not functionName:
            return JsonResponse(
                {"success": False, "error": "Missing 'function' field."},
                status=400,
            )

        if functionName == "bookAppointment":
            result = bookAppointmentLogic(arguments)
        elif functionName == "cancelAppointment":
            result = cancelAppointmentLogic(arguments)
        elif functionName == "rescheduleAppointment":
            result = rescheduleAppointmentLogic(arguments)
        elif functionName == "getAvailableSlots":
            result = getAvailableSlotsLogic(arguments)
        else:
            return JsonResponse(
                {"success": False, "error": f"Unknown function: {functionName}"},
                status=400,
            )

        httpStatus = 200 if result.get("success") else 400
        return JsonResponse(result, status=httpStatus)