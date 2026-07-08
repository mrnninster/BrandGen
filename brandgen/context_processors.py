from brandgen.services.api_keys import session_key_status


def api_key_context(request):
    return {"api_key": session_key_status(request.session)}
