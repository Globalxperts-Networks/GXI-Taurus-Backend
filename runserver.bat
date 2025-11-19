python manage.py makemigrations
python manage.py migrate
python manage.py runserver 127.0.0.1:8080

celery -A restserver worker -l info -c 10 

uvicorn restserver.asgi:application --host 0.0.0.0 --port 8005 --reload


@REM python test.py --mode onlineMeeting --organizer-object-id 34d9ca2c-66cf-47e8-8ea6-445b52b538a4 --start "2025-11-20T10:00:00Z" --end "2025-11-20T10:30:00Z" --send-email


@REM python test.py \
@REM   --mode calendarEvent \
@REM   --organizer-upn organizer@yourtenant.com \
@REM   --start "2025-11-20T10:00:00" \
@REM   --end "2025-11-20T11:00:00" \
@REM   --attendees "jaijhavats32@gmail.com,jaijhavats95@gmail.com" \
@REM   --send-email
