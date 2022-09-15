from django.http import QueryDict
from django.db import models
from rest_framework.serializers import Serializer
from rest_framework import fields


class GenericSerializer(Serializer):
    def create(self, validated_data):
        pass

    def update(self, instance, validated_data):
        pass

    def validate(self, data: QueryDict):
        """
        Custom Generic Validator
        :param data: querydict passed from the request
        :return: the final dict
        """
        final_data = {}

        # only gets fields from the immediate serializer...
        local_fields = self.get_fields()

        if not local_fields or type(self) is GenericModelSerializer:
            # all fields currently defined in serializer
            my_fields = self.fields

            # if this is a model serializer, the extra fields cannot be directly serialized
            if type(self) is GenericModelSerializer and local_fields:
                for key in local_fields.keys():
                    if key in my_fields.keys():
                        my_fields.pop(key)
        else:
            my_fields = local_fields

        for key in data.keys():
            if key in my_fields.keys():
                if data[key] == "" or data[key] is None:
                    final_data[key] = my_fields[key].default
                else:
                    final_data[key] = data[key]
        return super(GenericSerializer, self).validate(final_data)

    def get_data(self, key: str, default_value='___INVALID_KEY'):
        """
        Check serializer data. Forces validation if unvalidated. Please perform validation before coming here.
        :param key: serializer key to check
        :param default_value: the value to return if key is not found
        :return: requested data or ___VALIDATION_FAILED or ___INVALID_KEY
        """
        try:
            data = self.data
        except AssertionError:  # in case the data has not yet been validated...
            if not self.is_valid():  # perform validation
                return '___VALIDATION_FAILED'

        return self.data.get(key, default_value)

    def has_key(self, key: str):
        """
        Modified from the dict_has_key method to evaluate serializer data directly.
        Check if the object is not None, if the object is a dictionary, and if the key exists all in one go.
        :param key: the key to check for
        :return: True/False
        """
        return True if self.get_data(key) not in ['___INVALID_KEY', '___VALIDATION_FAILED'] else False

    def key_has_data(self, key: str):
        """
        Modified from the dict_has_key method to evaluate serializer data directly.
        Check if the object is not None, if the object is a dictionary,
        if the key exists, and if it has a value all in one go.
        :param key: the key to check for
        :return: True/False
        """
        str_data = str(self.get_data(key))
        return True if str_data not in [
            '___INVALID_KEY', '___VALIDATION_FAILED', "<class 'rest_framework.fields.empty'>"] else False

    def keys_have_data(self, keys: list):
        """
        Modified from the dict_has_key method to evaluate serializer data directly.
        Check if the object is not None, if the object is a dictionary,
        if the keys exist, and if they have values all in one go.
        :param keys: the keys to check for
        :return: True/False
        """
        if keys:
            for key in keys:
                if not self.key_has_data(key):
                    return False
            return True
        return False

    @staticmethod
    def attr_or_key_has_data(obj, attribute_or_key):
        """
        This doesn't care what kind of object we have. Object, or dict.
        :param obj: the object to check
        :param attribute_or_key: check for attribute, and then check for key
        :return: True/False
        """
        value = getattr(obj, attribute_or_key, '___INVALID_KEY') \
            if hasattr(obj, attribute_or_key) and not type(obj) is dict else \
            obj.get(attribute_or_key, '___INVALID_KEY')
        return True if value != '___INVALID_KEY' else False
    
    
class GenericModelSerializer(GenericSerializer):
    """
    Created to speed up admin view creation
    """
    read_only = True
    default = None
    parent = None
    serialize_level = 0
    serializer_field_mapping = {
        models.AutoField: fields.IntegerField,
        models.BigIntegerField: fields.IntegerField,
        models.CharField: fields.CharField,
        models.CommaSeparatedIntegerField: fields.CharField,
        models.DateField: fields.DateField,
        models.DateTimeField: fields.DateTimeField,
        models.EmailField: fields.EmailField,
        models.Field: fields.ModelField,
        models.FileField: fields.FileField,
        models.FloatField: fields.FloatField,
        models.ImageField: fields.ImageField,
        models.IntegerField: fields.IntegerField,
        models.PositiveIntegerField: fields.IntegerField,
        models.PositiveSmallIntegerField: fields.IntegerField,
        models.SlugField: fields.SlugField,
        models.SmallIntegerField: fields.IntegerField,
        models.TextField: fields.CharField,
        models.TimeField: fields.TimeField,
        models.URLField: fields.URLField,
        models.GenericIPAddressField: fields.IPAddressField,
        models.FilePathField: fields.FilePathField,
        models.ManyToManyField: fields.CharField,
    }

    @classmethod
    def default_valid(cls, default_value):
        return True if not default_value == models.fields.NOT_PROVIDED \
                       and not type(default_value) in cls.serializer_field_mapping else False

    def __init__(self, model, instance=None, data: dict = fields.empty, **kwargs):
        # model._meta.get_fields() returns ManyToManyRel -- which is not really what we want...
        # all_fields = model._meta.get_fields()
        all_fields = model.get_fields()  # custom method

        # Auto-Serialization of subfields -- requires a key field to be defined to save
        if data is not fields.empty and (type(data) is dict or type(data) is QueryDict):
            for k, v in data.items():
                if '__' in k:
                    sp = str(k).split('__')
                    for field in all_fields:
                        if sp[0] == field.name:
                            my_field = fields.CharField(
                                label=k, required=False,
                                default='',
                                allow_null=True)
                            my_name = k
                            self.fields[my_name] = my_field
                            setattr(self, my_name, my_field)
                            break

        if 'serialize_level' in kwargs and type(kwargs['serialize_level']) is int:
            self.serialize_level = kwargs['serialize_level']
            kwargs.pop('serialize_level')

        exclude_list = kwargs.pop('exclude', [])

        for field in all_fields:
            my_type = type(field)
            my_field = None
            my_name = None
            if my_type in self.serializer_field_mapping:
                my_field = self.serializer_field_mapping[type(field)](
                    label=field.verbose_name, required=False,
                    default=field.default if self.default_valid(field.default) else None,
                    allow_null=True)
                my_name = field.name
            elif my_type is models.DecimalField:
                my_field = models.DecimalField(
                    label=field.verbose_name, required=False,
                    default=field.default if self.default_valid(field.default) else None,
                    allow_null=True, max_digits=12 if not hasattr(field, 'max_digits') else field.max_digits,
                    decimal_places=2 if not hasattr(field, 'decimal_places') else field.decimal_places)
                my_name = field.name
            elif my_type is models.BooleanField or my_type is models.NullBooleanField:
                my_field = fields.NullBooleanField(
                    label=field.verbose_name, required=False,
                    default=field.default if self.default_valid(field.default) else None)
                my_name = field.name

            # or my_type is CurrentUserField
            elif my_type is models.ForeignKey or my_type is models.OneToOneField:
                if self.serialize_level >= 0:
                    my_field = fields.IntegerField(
                        label=field.verbose_name, required=False, allow_null=True,
                        default=field.default if self.default_valid(field.default) else None)
                    my_name = "{0}_id".format(field.name)
                else:
                    my_name = field.name
                    my_field = fields.CharField(
                        label=field.verbose_name, required=False, allow_null=True,
                        default=field.default if self.default_valid(field.default) else None)
            else:
                print("GenericModelSerializer: Field has no mapping!! {0} ({1})".format(field.name, str(my_type)))
            if my_field and my_name not in exclude_list:
                self.fields[my_name] = my_field
                setattr(self, my_name, my_field)
                if self.serialize_level >= 0 and my_type is models.ForeignKey or my_type is models.OneToOneField:
                    sub_model = getattr(model, field.name).field.related_model if hasattr(model, field.name) else None
                    if sub_model:
                        sub_names = []
                        try:
                            sub_fields = sub_model.get_fields()
                        except AttributeError:  # Special case for the Permission model
                            sub_fields = sub_model._meta.fields
                        if sub_fields:
                            sub_names = [sf.name for sf in sub_fields]  # subfield names from the foreign model...
                            sub_property_names = [name for name in dir(sub_model)  # sub properties
                                                  if isinstance(getattr(sub_model, name), property)]
                            # getting properties now!!
                            sub_names.extend(sub_property_names)

                        self.add_sub_fields(field, sub_names, ['name', 'value', 'tooltip', 'color', 'active',
                                                               'icon_class', 'active', 'order'])

        if type(instance) is model:
            self.instance = instance
        else:
            self.instance = None
        if data is not fields.empty:
            self.initial_data = data
        elif data is fields.empty and self.instance:
            self.initial_data = self.to_representation(self.instance)
            for k in list(self.initial_data.keys()).copy():
                if type(self.initial_data[k]) in self.serializer_field_mapping:
                    self.initial_data.pop(k)
            # assert self.is_valid(), "Assertion Failed! The model data could not be validated!"
        self.partial = kwargs.pop('partial', False)
        self._context = kwargs.pop('context', {})
        kwargs.pop('many', None)
        super(GenericSerializer, self).__init__(**kwargs)

    def update(self, instance, validated_data):
        return instance

    def to_representation(self, instance):
        """
        This is the method that actually serializes the models
        :param instance: model instance or dict in some cases
        :return: dict containing values
        """
        from datetime import date, datetime
        from mixins import BaseModel
        # from core.util import attrvalue
        # from core.timezone import date_to_string
        final = {}
        if issubclass(instance.__class__, BaseModel):
            instance: BaseModel
            try:
                all_fields = instance.get_fields()
            except AttributeError:  # Special case for the Permission model
                all_fields = instance.get_meta().fields

            allowed_fields = instance.serialize_levels(self.serialize_level) if hasattr(instance, 'serialize_levels') \
                else []
            if not allowed_fields:
                allowed_fields = list(self.fields.keys())

            for field in all_fields:
                if field.name in allowed_fields:
                    my_type = type(field)

                    # or my_type is CurrentUserField:
                    if my_type is models.ForeignKey or my_type is models.OneToOneField:
                        if self.serialize_level > 0:
                            try:
                                model = getattr(instance, field.name).field.related_model
                                obj = getattr(instance, field.name)
                                final[field.name] = GenericModelSerializer(
                                    model, obj, serialize_level=self.serialize_level - 1).initial_data if obj else None
                            except Exception as ex:
                                print(f'Warning: "{field.name}" Object cannot be serialized.', repr(ex))
                                final[field.name] = None
                        else:
                            # return the name with _id -- depreciated
                            field_name = "{0}_id".format(field.name)
                            if self.attr_or_key_has_data(instance, field_name):
                                final[field.name] = getattr(instance, field_name)

                    elif my_type is models.ManyToManyField:
                        # csv
                        if self.serialize_level > 0:
                            m2m_field = getattr(instance, field.name)
                            m2m_model = getattr(instance, field.name).model
                            final[field.name] = [GenericModelSerializer(
                                m2m_model, obj, serialize_level=self.serialize_level - 1).initial_data
                                                 if obj else None
                                                 for obj in m2m_field.all()]
                        else:
                            final[field.name] = instance.many_to_csv(getattr(instance, field.name))
                    else:
                        if self.attr_or_key_has_data(instance, field.name):
                            from utils import DateUtil
                            value = getattr(instance, field.name)
                            if type(value) is date:
                                final[field.name] = DateUtil.date_to_string(value)
                            elif type(value) is datetime:
                                final[field.name] = DateUtil.date_to_string(value, True, False, True)
                            else:
                                final[field.name] = value
                elif "{0}_id".format(field.name) in self.fields:
                    this_obj = None
                    try:
                        this_obj = getattr(instance, field.name)
                    except Exception as ex:
                        err_field_name = f"{field.name}_id"
                        print(f'Warning: Object cannot be serialized. '
                              f'Field: "{err_field_name}" Value:{str(getattr(instance, err_field_name, "?ERR"))} '
                              f'{repr(ex)}')
                    if this_obj:
                        self.add_field_values(this_obj, final, field, ['id', 'name', 'value', 'tooltip', 'color',
                                                                       'active', 'icon_class', 'active', 'order'])

            if final and 'name' not in final:
                if hasattr(instance, 'name'):
                    final['name'] = instance.name
            if final and 'repr' not in final:  # added generic string representation
                final['repr'] = str(instance)

        return final if type(instance) is not dict else instance

    @classmethod
    def add_field_values(cls, this_obj, final, field, field_list):
        for f in field_list:
            if cls.attr_or_key_has_data(this_obj, f):
                field_name = "{0}_{1}".format(field.name, f if f == 'id' else "_{0}".format(f))
                final[field_name] = getattr(this_obj, f)

    def add_sub_fields(self, field, sub_names, field_list):
        for f in field_list:
            sub_field_name = "{0}__{1}".format(field.name, f)

            if sub_field_name in sub_names:
                sub_field = fields.CharField(label="{0} {1}".format(field.verbose_name, str(f).capitalize()),
                                             required=False, default=None, allow_null=True)
                self.fields[sub_field_name] = sub_field
                setattr(self, sub_field_name, sub_field)
