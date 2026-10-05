FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Arynwood-Technology/arynwood-chat-window" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
RUN useradd --system --uid 10001 --home-dir /data --create-home chatwindow
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY chat_window ./chat_window
RUN pip install --no-cache-dir . && rm -rf /app/build
USER chatwindow
WORKDIR /data
ENV CHAT_WINDOW_SITES=/sites CHAT_WINDOW_DATA=/data CHAT_WINDOW_HOST=0.0.0.0 CHAT_WINDOW_PORT=8790 \
    PYTHONUNBUFFERED=1
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/v1/health', timeout=3)"
ENTRYPOINT ["chat-window"]
CMD ["serve"]
