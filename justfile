build:
	uv build

serve:
	uv run litestar --app novamoc.asgi:create_app run

clean:
	rm -r dist
