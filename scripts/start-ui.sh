#!/bin/sh
set -eu
export API_URL="http://${API_HOST:?Set API_HOST}:${API_PORT:-8000}"
exec streamlit run ui/app.py --server.address=0.0.0.0 --server.port="${PORT:-10000}"
