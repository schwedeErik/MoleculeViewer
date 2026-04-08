"""
Minimal Protobuf module for `molecules.proto`, without requiring `protoc`.

The previous version embedded invalid bytes into AddSerializedFile, which caused:
TypeError: Couldn't parse file content!
"""

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

_sym_db = _symbol_database.Default()


def _build_file_descriptor_proto() -> _descriptor_pb2.FileDescriptorProto:
    fd = _descriptor_pb2.FileDescriptorProto()
    fd.name = "molecules.proto"
    fd.package = "molecule"
    fd.syntax = "proto3"

    # message Point { int64 id = 1; double lng = 2; double lat = 3; }
    msg_point = fd.message_type.add()
    msg_point.name = "Point"

    f_id = msg_point.field.add()
    f_id.name = "id"
    f_id.number = 1
    f_id.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f_id.type = _descriptor_pb2.FieldDescriptorProto.TYPE_INT64

    f_lng = msg_point.field.add()
    f_lng.name = "lng"
    f_lng.number = 2
    f_lng.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f_lng.type = _descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE

    f_lat = msg_point.field.add()
    f_lat.name = "lat"
    f_lat.number = 3
    f_lat.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f_lat.type = _descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE

    # message Points { repeated Point points = 1; }
    msg_points = fd.message_type.add()
    msg_points.name = "Points"

    f_points = msg_points.field.add()
    f_points.name = "points"
    f_points.number = 1
    f_points.label = _descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_points.type = _descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_points.type_name = ".molecule.Point"

    return fd


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    _build_file_descriptor_proto().SerializeToString()
)

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "molecules_pb2", _globals)

Point = _globals["Point"]
Points = _globals["Points"]

