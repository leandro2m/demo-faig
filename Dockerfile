# Runtime configuration (no secrets baked into this image — pass at `docker run` / k8s time):
#   FAIG_URL          (required) FortiAIGate base URL, e.g. https://<fortiaigate-ip>
#   FAIG_PATH         (optional) defaults to /v1/chat-support
#   FAIG_API_KEY      (required) FortiAIGate bearer token
#   FAIG_MODEL        (optional) defaults to openai.gpt-oss-120b-1:0
#   FAIG_VERIFY_TLS   (optional) defaults to false
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py fortiaigate_model.py vulnerable_mcp.py .
COPY assets/ ./assets/

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
