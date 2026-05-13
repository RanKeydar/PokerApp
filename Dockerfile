# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.12

FROM python:${PYTHON_VERSION}-slim

LABEL fly_launch_runtime="flask"

WORKDIR /code
ENV PYTHONPATH=/code/src

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:10000"]

