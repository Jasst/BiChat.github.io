"""
schemas.py — Схемы валидации входящих данных (Marshmallow)
"""
from marshmallow import Schema, fields, ValidationError, post_load


class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(
        required=True, load_only=True,
        validate=lambda x: len(x.strip()) >= 24,
    )

    @post_load
    def strip(self, data, **kwargs):
        data['mnemonic_phrase'] = data['mnemonic_phrase'].strip()
        return data


class MessageSchema(Schema):
    recipient    = fields.Str(required=True,
                               validate=lambda x: len(x) == 64 or x.startswith('group:'))
    content      = fields.Str(required=True, allow_none=False)
    image        = fields.Str(allow_none=True)
    message_type = fields.Str(load_default='direct',
                               validate=lambda x: x in ('direct', 'group'))
    group_id     = fields.Str(allow_none=True)


class GroupSchema(Schema):
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 100)
    members = fields.List(fields.Str(), required=True,
                           validate=lambda x: 1 <= len(x) <= 50)


class ContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x) <= 50)


class EditContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 50)

    @post_load
    def strip_fields(self, data, **kwargs):
        data['name']    = data['name'].strip()
        data['address'] = data['address'].strip().lower()
        return data


class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)
