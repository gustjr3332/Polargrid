# Controller image: the polagrid package and the ACP hardening script. Build context: sw/edge_ai.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==1.26.4 scipy==1.11.4 scikit-learn==1.9.1 requests==2.31.0
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY polagrid/ polagrid/
COPY tools/harden_acp.py tools/harden_acp.py
