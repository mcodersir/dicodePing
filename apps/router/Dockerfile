FROM --platform=$BUILDPLATFORM golang:1.27.3-alpine AS build
ARG TARGETARCH
RUN apk add --no-cache git
WORKDIR /fox
COPY apps/fox-helper/ .
RUN CGO_ENABLED=0 GOOS=linux GOARCH="$TARGETARCH" go build -mod=readonly -trimpath -ldflags="-s -w -X main.version=5.0.9" -o /out/dicode-fox .
WORKDIR /sing-box
RUN git init && git fetch --depth 1 https://github.com/SagerNet/sing-box.git a713aee3058f97f3facc98e85244a3e73c82dca1 \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = a713aee3058f97f3facc98e85244a3e73c82dca1 \
    && CGO_ENABLED=0 GOOS=linux GOARCH="$TARGETARCH" go build -mod=readonly -trimpath \
    -ldflags='-s -w -X github.com/sagernet/sing-box/constant.Version=1.14.6' \
    -o /out/sing-box ./cmd/sing-box

FROM python:3.14-alpine
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ /usr/local/bin/
COPY apps/router/dicode-router.py /usr/local/bin/dicode-router
COPY LICENSE licenses/LICENSE-sing-box apps/fox-helper/LICENSE-ArmanVPN.txt apps/fox-helper/LICENSE-FoxyVPN.txt /usr/share/licenses/dicodeping/
RUN chmod 755 /usr/local/bin/dicode-router
VOLUME ["/data"]
EXPOSE 10810
ENTRYPOINT ["/usr/local/bin/dicode-router", "run"]
