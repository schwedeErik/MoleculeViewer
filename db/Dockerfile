FROM postgis/postgis:16-3.4

# Install pgvector from source so `CREATE EXTENSION vector;` works.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    build-essential \
    postgresql-server-dev-16 \
    clang-13 \
    llvm-13 \
  && rm -rf /var/lib/apt/lists/*

RUN git clone --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
  && cd /tmp/pgvector \
  && make \
  && make install \
  && rm -rf /tmp/pgvector

