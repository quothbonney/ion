import datetime
import logging

from django import http
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import exceptions
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AdminEventForm, EventForm
from .models import Event

from ..auth.decorators import deny_restricted
from ...utils.html import safe_html
from ...utils.helpers import get_id

logger = logging.getLogger(__name__)


@login_required
@deny_restricted
def events_view(request):
    """Events homepage.

    Shows a list of events occurring in the next week, month, and
    future.

    """

    is_events_admin = request.user.has_admin_permission('events')

    if request.method == "POST":
        if "approve" in request.POST and is_events_admin:
            event_id = request.POST.get('approve')
            event = get_object_or_404(Event, id=event_id)
            event.rejected = False
            event.approved = True
            event.approved_by = request.user
            event.save()
            messages.success(request, "Approved event {}".format(event))

        if "reject" in request.POST and is_events_admin:
            event_id = request.POST.get('reject')
            event = get_object_or_404(Event, id=event_id)
            event.approved = False
            event.rejected = True
            event.rejected_by = request.user
            event.save()
            messages.success(request, "Rejected event {}".format(event))

    if is_events_admin and "show_all" in request.GET:
        viewable_events = (Event.objects.all().this_year().prefetch_related("groups"))
    else:
        viewable_events = (Event.objects.visible_to_user(request.user).this_year().prefetch_related("groups"))

    # get date objects for week and month
    today = datetime.date.today()
    delta = today - datetime.timedelta(days=today.weekday())
    this_week = (delta, delta + datetime.timedelta(days=7))
    this_month = (this_week[1], this_week[1] + datetime.timedelta(days=31))

    events_categories = [{
        "title": "This week",
        "events": viewable_events.filter(time__gte=this_week[0], time__lt=this_week[1])
    }, {
        "title": "This month",
        "events": viewable_events.filter(time__gte=this_month[0], time__lt=this_month[1])
    }, {
        "title": "Future",
        "events": viewable_events.filter(time__gte=this_month[1])
    }]

    if is_events_admin:
        unapproved_events = (Event.objects.filter(approved=False, rejected=False).prefetch_related("groups"))
        events_categories = [{"title": "Awaiting Approval", "events": unapproved_events}] + events_categories

    if is_events_admin and "show_all" in request.GET:
        events_categories.append({"title": "Past", "events": viewable_events.filter(time__lt=this_week[0])})

    context = {
        "events": events_categories,
        "num_events": sum([x["events"].count() for x in events_categories]),
        "is_events_admin": is_events_admin,
        "show_attend": True,
        "show_icon": True
    }
    return render(request, "events/home.html", context)


@login_required
@deny_restricted
def join_event_view(request, event_id):
    """Join event page. If a POST request, actually add or remove the attendance of the current
    user. Otherwise, display a page with confirmation.

    event_id: event id

    """

    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        if not event.show_attending:
            return redirect("events")
        if "attending" in request.POST:
            attending = request.POST.get("attending")
            attending = (attending == "true")

            if attending:
                event.attending.add(request.user)
            else:
                event.attending.remove(request.user)

            return redirect("events")

    context = {"event": event, "is_events_admin": request.user.has_admin_permission('events')}
    return render(request, "events/join_event.html", context)


@login_required
@deny_restricted
def event_roster_view(request, event_id):
    """Show the event roster. Users with hidden eighth period permissions will not be displayed.
    Users will be able to view all other users, along with a count of the number of hidden users.
    (Same as 8th roster page.) Admins will see a full roster at the bottom.

    event_id: event id

    """

    event = get_object_or_404(Event, id=event_id)

    full_roster = list(event.attending.all())
    viewable_roster = []
    num_hidden_members = 0
    for p in full_roster:
        if p.can_view_eighth:
            viewable_roster.append(p)
        else:
            num_hidden_members += 1

    context = {
        "event": event,
        "viewable_roster": viewable_roster,
        "full_roster": full_roster,
        "num_hidden_members": num_hidden_members,
        "is_events_admin": request.user.has_admin_permission('events'),
    }
    return render(request, "events/roster.html", context)


@login_required
@deny_restricted
def add_event_view(request):
    """Add event page.

    Currently, there is an approval process for events. If a user is an
    events administrator, they can create events directly. Otherwise,
    their event is added in the system but must be approved.

    """
    is_events_admin = request.user.has_admin_permission('events')
    if not is_events_admin:
        return redirect("request_event")

    if request.method == "POST":
        form = EventForm(data=request.POST, all_groups=request.user.has_admin_permission('groups'))
        logger.debug(form)
        if form.is_valid():
            obj = form.save()
            obj.user = request.user
            # SAFE HTML
            obj.description = safe_html(obj.description)

            # auto-approve if admin
            obj.approved = True
            obj.approved_by = request.user
            messages.success(request, "Because you are an administrator, this event was auto-approved.")
            obj.created_hook(request)

            obj.save()
            return redirect("events")
        else:
            messages.error(request, "Error adding event.")
    else:
        form = EventForm(all_groups=request.user.has_admin_permission('groups'))
    context = {"form": form, "action": "add", "action_title": "Add" if is_events_admin else "Submit", "is_events_admin": is_events_admin}
    return render(request, "events/add_modify.html", context)


@login_required
@deny_restricted
def request_event_view(request):
    """Request event page.

    Currently, there is an approval process for events. If a user is an
    events administrator, they can create events directly. Otherwise,
    their event is added in the system but must be approved.

    """
    is_events_admin = False

    if request.method == "POST":
        form = EventForm(data=request.POST, all_groups=request.user.has_admin_permission('groups'))
        logger.debug(form)
        if form.is_valid():
            obj = form.save()
            obj.user = request.user
            # SAFE HTML
            obj.description = safe_html(obj.description)

            messages.success(request,
                             "Your event needs to be approved by an administrator. If approved, it should appear on Intranet within 24 hours.")
            obj.created_hook(request)

            obj.save()
            return redirect("events")
        else:
            messages.error(request, "Error adding event.")
    else:
        form = EventForm(all_groups=request.user.has_admin_permission('groups'))
    context = {"form": form, "action": "request", "action_title": "Submit", "is_events_admin": is_events_admin}
    return render(request, "events/add_modify.html", context)


@login_required
@deny_restricted
def modify_event_view(request, event_id=None):
    """Modify event page. You may only modify an event if you were the creator or you are an
    administrator.

    event_id: event id

    """
    event = get_object_or_404(Event, id=event_id)
    is_events_admin = request.user.has_admin_permission('events')

    if not is_events_admin:
        raise exceptions.PermissionDenied

    if request.method == "POST":
        if is_events_admin:
            form = AdminEventForm(data=request.POST, instance=event, all_groups=request.user.has_admin_permission('groups'))
        else:
            form = EventForm(data=request.POST, instance=event, all_groups=request.user.has_admin_permission('groups'))
        logger.debug(form)
        if form.is_valid():
            obj = form.save()
            # SAFE HTML
            obj.description = safe_html(obj.description)
            obj.save()
            messages.success(request, "Successfully modified event.")
            # return redirect("events")
        else:
            messages.error(request, "Error modifying event.")
    else:
        if is_events_admin:
            form = AdminEventForm(instance=event, all_groups=request.user.has_admin_permission('groups'))
        else:
            form = EventForm(instance=event, all_groups=request.user.has_admin_permission('groups'))
    context = {"form": form, "action": "modify", "action_title": "Modify", "id": event_id, "is_events_admin": is_events_admin}
    return render(request, "events/add_modify.html", context)


@login_required
@deny_restricted
def delete_event_view(request, event_id):
    """Delete event page. You may only delete an event if you are an
    administrator. Confirmation page if not POST.

    event_id: event id

    """
    event = get_object_or_404(Event, id=event_id)
    if not request.user.has_admin_permission('events'):
        raise exceptions.PermissionDenied

    if request.method == "POST":
        try:
            event.delete()
            messages.success(request, "Successfully deleted event.")
        except Event.DoesNotExist:
            pass

        return redirect("events")
    else:
        return render(request, "events/delete.html", {"event": event})


@login_required
@deny_restricted
def show_event_view(request):
    """ Unhide an event that was hidden by the logged-in user.

        events_hidden in the user model is the related_name for
        "users_hidden" in the EventUserMap model.
    """
    if request.method == "POST":
        event_id = get_id(request.POST.get("event_id", None))
        if event_id:
            event = get_object_or_404(Event, id=event_id)
            event.user_map.users_hidden.remove(request.user)
            event.user_map.save()
            return http.HttpResponse("Unhidden")
        raise http.Http404
    else:
        return http.HttpResponseNotAllowed(["POST"], "HTTP 405: METHOD NOT ALLOWED")


@login_required
@deny_restricted
def hide_event_view(request):
    """ Hide an event for the logged-in user.

        events_hidden in the user model is the related_name for
        "users_hidden" in the EventUserMap model.
    """
    if request.method == "POST":
        event_id = get_id(request.POST.get("event_id", None))
        if event_id:
            event = get_object_or_404(Event, id=event_id)
            event.user_map.users_hidden.add(request.user)
            event.user_map.save()
            return http.HttpResponse("Hidden")
        raise http.Http404
    else:
        return http.HttpResponseNotAllowed(["POST"], "HTTP 405: METHOD NOT ALLOWED")
