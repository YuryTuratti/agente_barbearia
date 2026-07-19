from fastapi.routing import APIRoute

from app.main import app


def test_evolution_webhook_post_route_is_registered() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/webhooks/evolution", "POST") in routes


def test_admin_routes_are_registered() -> None:
    paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    assert "/admin/dashboard" in paths
    assert "/admin/api/dashboard-summary" in paths
