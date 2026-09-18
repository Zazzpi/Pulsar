from functools import wraps

from django.db import connections
from django.http import JsonResponse
from django.utils import timezone

from accounts.authentication import bearer_required

from .models import ClientDailyMetric, ClientNote, ClientWatch
from .services import WmsUnavailable, cached_read, start_watch
from .validation import InvalidInput, date_range, json_body, pagination, positive_int


class NotFound(Exception):
    pass


def api_endpoint(*methods):
    def decorate(view):
        @bearer_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                response = JsonResponse({"error": "Метод не поддерживается."}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            try:
                return view(request, *args, **kwargs)
            except InvalidInput as exc:
                return JsonResponse({"error": str(exc)}, status=400)
            except NotFound:
                return JsonResponse({"error": "Объект не найден."}, status=404)
            except WmsUnavailable:
                return JsonResponse({"error": "WMS временно недоступна. Повторите позже."}, status=503)

        return wrapped
    return decorate


def require_client(client_id):
    positive_int(client_id, "client_id")
    client = cached_read("client", client_id=client_id)
    if client is None:
        raise NotFound
    return client


def health(request):
    if request.method != "GET":
        return JsonResponse({"error": "Требуется GET."}, status=405)
    # Health reports only the app DB: mock mode never needs a WMS connection.
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})


@api_endpoint("GET")
def clients(request):
    page, page_size = pagination(request)
    search = request.GET.get("q", "").strip()
    if len(search) > 200:
        raise InvalidInput("Поисковая строка не должна превышать 200 символов.")
    return JsonResponse(cached_read("clients", search=search, page=page, page_size=page_size))


@api_endpoint("GET")
def summary(request, client_id):
    require_client(client_id)
    return JsonResponse(cached_read("summary", client_id=client_id))


@api_endpoint("GET")
def detail(request, client_id, resource):
    if resource not in {"stock", "orders", "receivings", "shipments", "movements"}:
        raise NotFound
    page, page_size = pagination(request)
    params = {"client_id": client_id, "page": page, "page_size": page_size}
    if resource != "stock":
        params["date_from"], params["date_to"] = date_range(request)
    elif "from" in request.GET or "to" in request.GET:
        raise InvalidInput("Остатки показывают текущее состояние и не фильтруются по датам.")
    require_client(client_id)
    return JsonResponse(cached_read(resource, **params))


def watch_data(watch):
    return {
        "id": watch.pk,
        "wms_client_id": watch.wms_client_id,
        "client": cached_read("client", client_id=watch.wms_client_id),
        "started_at": watch.started_at,
        "ends_at": watch.ends_at,
        "is_active": watch.is_active and watch.ends_at > timezone.now(),
    }


@api_endpoint("GET", "POST")
def watches(request):
    if request.method == "POST":
        client_id = positive_int(json_body(request).get("wms_client_id"), "wms_client_id")
        require_client(client_id)
        watch, created = start_watch(request.api_user, client_id)
        return JsonResponse(watch_data(watch), status=201 if created else 200)
    page, page_size = pagination(request)
    offset = (page - 1) * page_size
    queryset = ClientWatch.objects.filter(user=request.api_user, is_active=True)
    if "wms_client_id" in request.GET:
        queryset = queryset.filter(wms_client_id=positive_int(
            request.GET["wms_client_id"], "wms_client_id",
        ))
    rows = list(queryset[offset:offset + page_size + 1])
    return JsonResponse({
        "results": [watch_data(row) for row in rows[:page_size]],
        "page": page, "page_size": page_size, "has_next": len(rows) > page_size,
    })


@api_endpoint("DELETE")
def watch(request, watch_id):
    positive_int(watch_id, "watch_id")
    changed = ClientWatch.objects.filter(pk=watch_id, user=request.api_user).update(is_active=False)
    if not changed:
        raise NotFound
    return JsonResponse({"ok": True})


def note_data(note):
    return {"id": note.pk, "body": note.body, "created_at": note.created_at}


@api_endpoint("GET", "POST")
def notes(request, client_id):
    require_client(client_id)
    if request.method == "POST":
        body = json_body(request).get("body", "")
        if not isinstance(body, str) or not 1 <= len(body.strip()) <= 5000:
            raise InvalidInput("Заметка должна содержать от 1 до 5000 символов.")
        note = ClientNote.objects.create(
            user=request.api_user, wms_client_id=client_id, body=body.strip(),
        )
        return JsonResponse(note_data(note), status=201)
    page, page_size = pagination(request)
    offset = (page - 1) * page_size
    rows = list(ClientNote.objects.filter(user=request.api_user, wms_client_id=client_id)[
        offset:offset + page_size + 1
    ])
    return JsonResponse({
        "results": [note_data(row) for row in rows[:page_size]],
        "page": page, "page_size": page_size, "has_next": len(rows) > page_size,
    })


@api_endpoint("GET")
def metrics(request, client_id):
    page, page_size = pagination(request)
    date_from, date_to = date_range(request)
    require_client(client_id)
    offset = (page - 1) * page_size
    rows = list(ClientDailyMetric.objects.filter(
        wms_client_id=client_id, date__gte=date_from, date__lt=date_to,
    ).values()[offset:offset + page_size + 1])
    return JsonResponse({
        "results": rows[:page_size], "page": page, "page_size": page_size,
        "has_next": len(rows) > page_size,
    })
