"""gRPC .proto şemaları + üretilen kod. `host_bridge.proto`'nun tek elle
yazılan kaynağı — `host_bridge_pb2.py`/`host_bridge_pb2_grpc.py` üretilir,
COMMIT edilir (bu repo'da build adımı yok, kurulum sırasında üretilemez).

Yeniden üretmek için (`grpcio-tools` gerekir, sadece .proto'yu değiştirenin
makinesinde — runtime `grpcio` yeterli):

    cd py/claudeops/proto && python3 -m grpc_tools.protoc -I. \\
        --python_out=. --grpc_python_out=. host_bridge.proto

SONRA ELLE DÜZELT: `host_bridge_pb2_grpc.py`'nin protoc'un ürettiği
`import host_bridge_pb2 as host__bridge__pb2` satırı MUTLAK import — bu
paketin İÇİNDE kırılır. `from . import host_bridge_pb2 as host__bridge__pb2`
yap (bilinen protoc-plugin sınırlaması, her regen'de tekrar uygulanmalı)."""
