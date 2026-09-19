FROM --platform=linux/arm64 ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config zlib1g-dev libglib2.0-dev libcurl4-openssl-dev \
    libx11-xcb1 libxcb-xfixes0 libxcb-shape0 libxcb-shm0 libxcb-randr0 \
    libxcb-image0 libxcb-keysyms1 libxcb-xtest0 libdbus-1-3 libgbm1 libxfixes3 \
    libgl1 libdrm2 libgssapi-krb5-2 openssl ca-certificates libegl-mesa0 libsdl2-dev \
    libasound2 libasound2-plugins alsa-utils pulseaudio pulseaudio-utils dbus \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY demo /app/demo
RUN cmake -S /app/demo -B /app/demo/build && cmake --build /app/demo/build -j3
ENV LD_LIBRARY_PATH=/app/demo/bin:/app/demo/bin/qt_libs:/app/demo/bin/libglib2/lib
WORKDIR /app/demo/bin
CMD ["/bin/bash"]
