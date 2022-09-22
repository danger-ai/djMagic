
import json
import re

import django.db
from django.db import models, OperationalError
from django.core.exceptions import AppRegistryNotReady
from typing import Optional, List, Dict, Union, Type, Tuple
from django.db.models import Q, Count, QuerySet
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings as dj_cfg


class BaseModel(models.Model):
    id = models.BigAutoField(primary_key=True)

    objects: models.Manager

    def to_json(self):
        """
        Represent the current model object as a JSON object (fixed)
        :return: A JSON object string (many to many fields are represented by a csv id list)
        """
        super_serial_object = self.serialize_me()
        return json.dumps(super_serial_object, cls=DjangoJSONEncoder)

    @classmethod
    def model_identity(cls):
        """
        Agile Model ID
        :return: Model ID using the app, and model name
        """
        name = str(cls._meta.model_name).lower()
        return "{0}.{1}".format(str(cls._meta.app_label).lower(), name)

    @property
    def uid(self):
        """
        Agile Unique Model Object ID
        :return: Unique ID using the app, model name, and object ID
        """
        return "{0}.{1}".format(self.model_identity(), getattr(self, 'id', '0'))

    def get_custom_uid(self, name):
        """
        Generates a custom id using a given name and the UID
        """
        return f"{self.uid}.{name}"

    @classmethod
    def get_meta(cls):
        """
        Get model meta options for the current model
        """
        return cls._meta

    @classmethod
    def get_unique_together(cls):
        """
        Get the unique together fields for this model
        :return: the set of field names that must be unique_together -- returns None if not set
        """
        from django.apps import apps
        from django.contrib.contenttypes.models import ContentType
        # use the parent/base model meta definition if this is a proxy model
        if cls.get_meta().proxy:
            ct = ContentType.objects.get_for_model(cls)
            eval_model = apps.get_model(ct.app_label, ct.model)
        else:
            eval_model = cls

        unique_together = eval_model._meta.unique_together
        for field_set in unique_together:  # only returns the first set
            return field_set
        return None

    @classmethod
    def get_unique_eval(cls, init_obj: dict):
        final_eval = {}
        unique_fields = cls.get_unique_together()
        if unique_fields:
            for unique_field in unique_fields:
                if unique_field in init_obj:
                    final_eval[unique_field] = init_obj[unique_field]
                elif f'{unique_field}_id' in init_obj:
                    final_eval[f'{unique_field}_id'] = init_obj[f'{unique_field}_id']
        return final_eval

    @classmethod
    def dup_check(cls, model_obj):
        unique_fields = cls.get_unique_together()
        if unique_fields:
            query = {'id__ne': model_obj.id}
            for unique_field in unique_fields:
                query[unique_field] = getattr(model_obj, unique_field, None)
            record = cls.get(**query)
            return record if record else None
        return None

    def get_update_vals(self, data, updates, source_key, destination_key: str = None, id_exception_list=None):
        """
        Get the updated values by comparing an input dictionary and the current object
        :param data: input dictionary
        :param updates: previous update dictionary
        :param source_key: the name of the source key
        :param destination_key: the name of the model object attribute (optional)
        :param id_exception_list: ids are generally enforced as int type - exceptions skip the enforcement check
        :return:
        """
        from utils import is_valid_dict
        if id_exception_list is None:
            id_exception_list = []
        if not destination_key:
            destination_key = source_key
        if is_valid_dict(data, source_key):
            new_val = data[source_key]
            destination_key = f"{destination_key}_id" \
                if hasattr(self, f"{destination_key}_id") \
                   and (str(new_val).replace('-', '').isdecimal() or str(new_val).replace('-', '').isnumeric()) \
                else destination_key
            if new_val and hasattr(self, str(destination_key)) and not getattr(self, str(destination_key)) == new_val:
                # this skips the int type enforcement check if the key is on the list
                if str(destination_key) not in id_exception_list and \
                        str(destination_key).endswith("_id") and int(new_val) < 1:
                    if not getattr(self, destination_key) is None:
                        updates[destination_key] = None
                else:
                    updates[destination_key] = new_val
        return updates

    @classmethod
    def serialize(cls, obj_instance, serialization_level: int = 0):
        """
        Uses the GenericModelSerializer to serialize data contained within the model object
        :param obj_instance: Model Object Instance
        :param serialization_level: How much of the submodel data should be serialized?
        :return: Returns a dictionary object containing model record data.
        The returned field names are compatible with QuerySet objects.
        """
        from serializers import GenericModelSerializer
        return GenericModelSerializer(cls, obj_instance, serialize_level=serialization_level).initial_data

    def serialize_me(self, serialization_level: int = 0):
        """
        Return a dictionary and serialize objects up to a certain number of levels
        """
        return self.serialize(self, serialization_level)

    def validate_fk_field(self, field_name):
        """
        Used to validate the data in the foreign key field
        """
        if hasattr(self, f"{field_name}_id"):
            if getattr(self, f"{field_name}_id"):
                try:
                    field_obj = getattr(self, field_name)
                    return "Valid"
                except:
                    print(f"Field data validation failed ({field_name}).")
                    return "Invalid"
            else:
                return "NoVal"
        else:
            return "NoField"

    def valid_fix_fk_field(self, field_name):
        """
        Removes invalid foreign key references
        """
        validator = self.validate_fk_field(field_name)
        if validator == "Invalid":
            print(f"Foreign Key reference removed ({getattr(self, f'{field_name}_id')}).")
            setattr(self, f"{field_name}_id", None)
            self.save(update_fields=[field_name])
            return None
        elif not validator == "NoField":
            return getattr(self, field_name)
        else:
            return 0

    @classmethod
    def find_all_unused_records(cls, exclude_self_reference=True, limit: Optional[int] = None):
        """
        Find all unused records for the model
        """
        unused = []
        for record in cls.filter():
            if not record.find_in_use_records(exclude_self_reference):
                xr = record.get_all_xref()  # now checking xrefs as well --
                # there are other models that use other references...
                if not xr:
                    print(f"Record: {str(record)} is unused!")
                    unused.append(record)
            if limit is not None and len(unused) >= limit:
                break
        print(f"Found {len(unused)} records that are unused!")
        return unused

    @classmethod
    def find_all_used_records(cls, exclude_self_reference=True):
        """
        Find all referenced/used records for the model
        """
        used = {}
        for record in cls.all():
            usage = record.find_in_use_records(exclude_self_reference)
            if usage:
                print(f"Record: {str(record)} is used!")
                used[record] = usage
        print(f"{len(used)} records are in use!")
        return used

    def can_i_be_deleted(self, current_usage_instance: Optional['BaseModel'] = None):
        """
        Check if this model instance can be deleted without leaving orphan references
        :param current_usage_instance: a current model instance that references this model this usage will be excluded
            and must have the reference removed before this instance is deleted
        :return: I can/I can't as Boolean value
        """
        usages = self.find_in_use_records()
        blocked_delete = False
        if usages:
            blocked_delete = len(usages.keys()) > 1
            if not blocked_delete:
                for m, usage_list in usages.items():
                    if current_usage_instance and m.__class__.name == current_usage_instance.__class__.name and \
                            current_usage_instance.id in usage_list and len(usage_list) < 1:
                        print("Usage within spec.")
                    else:
                        blocked_delete = True
                        break
        return False if blocked_delete else True

    def find_in_use_records(self, exclude_self_reference=True):
        """
        Used to identify the foreign key usages of this particular record
        """
        from django.conf import settings
        from utils import ModelUtil
        from django.apps import apps
        from django.db.models import Q

        this_model = self.get_meta().model
        in_use_records = {}
        for app_name in settings.INSTALLED_APPS:
            if not app_name.startswith('django'):
                app_models = list(apps.get_app_config(app_name).get_models())
                for model in app_models:
                    if (exclude_self_reference and not model.__name__ == this_model.__name__) \
                            or not exclude_self_reference:

                        fk_fields = ModelUtil.find_ref_fields_from_objs(model, self)

                        if fk_fields:
                            q_filter = Q()
                            for field in fk_fields:
                                q_filter |= Q(**{f'{field}_id': self.id})
                            q = model.filter(q_filter)
                            if q:
                                in_use_records[model] = [r.id for r in q]

        return in_use_records if in_use_records else None

    @classmethod
    def get_fk_field_filters(cls, field_name: str, id_list):  # potential list field associated
        """
        Provide a list of ids to filter for the given field
        """
        if not type(id_list) == list:
            id_list = [id_list]
        filters = {"{0}__id__in".format(field_name): id_list}
        if hasattr(cls, "{0}_list".format(field_name)):
            filters["{0}_list__in".format(field_name)] = id_list
        return filters

    def copy_other_attribute(self, other_obj, attr, attr_other=None):
        """
        Copy an attribute from another object to the current instance
        :param other_obj: the object from which to copy
        :param attr: the attribute to compare on the current object
        :param attr_other: specify if the other attribute has a different name
        """
        from utils import ModelUtil
        ModelUtil.copy_attribute(self, other_obj, attr, attr_other)

    def copy_other_attributes(self, other_obj, attrs: Union[list, dict]):
        """
        Copy specified attributes from another object to the current instance
        :param other_obj: the object from which to copy
        :param attrs: can be a list of attributes, or a dictionary with {'this_attr': 'other_attr'} mappings
        """
        from utils import ModelUtil
        kwargs = {}
        if type(attrs) is list:
            kwargs['attr_dest_list'] = attrs
        elif type(attrs) is dict:
            kwargs['attr_dest_list'] = attrs.keys()
            kwargs['attr_source_list'] = attrs.values()

        ModelUtil.copy_attributes(self, other_obj, **kwargs)

    @classmethod
    def by_xref(cls, source_obj, source_id, org_id=None):
        """
        Get the model instance for the External Source Record ID
        @param source_obj: source value
        @param source_id: the source record id
        @param org_id:
        :return: instance of the model or None
        """
        xr = cls.get_model_xref(source_obj, source_id, org_id=org_id)
        if xr:
            return xr.instance
        return None

    @classmethod
    def parse_model_list(cls, data_list: list):
        """
        Parse a list of ids or a single id or a list of models and return a list of a model
        :param data_list: can be a list of ids, or a single id, or a list of models
        :return: a list of models based on the data_list
        """
        final_list = []
        if data_list and type(data_list) is list:
            if not hasattr(data_list[0], 'id'):
                if str(data_list[0]).isnumeric():
                    tmp_templates = []
                    for t in data_list:
                        if t not in [tmp.id for tmp in tmp_templates]:
                            template = cls.by_id(t)
                            if template:
                                tmp_templates.append(template)
                    final_list = tmp_templates
                elif str(data_list).isnumeric():
                    template = cls.by_id(data_list)
                    if template:
                        final_list = [template]
        return final_list

    @classmethod
    def is_field(cls, name) -> bool:
        """
        Checks for attribute, and then makes sure the attribute is a database field
        :param name: the field name to check for
        :return: boolean value
        """
        from django.core.exceptions import FieldDoesNotExist
        if hasattr(cls, name):
            meta = cls.get_meta()
            try:
                field = meta.get_field(name)
                return True
            except FieldDoesNotExist:
                return False
        return False

    @classmethod
    def all(cls):
        """uses .objects"""
        return cls.objects.all()

    @classmethod
    def get(cls, *args, **kwargs) -> Optional['BaseModel']:
        """
        Simple method to get first object

        available kwargs:
        qs_order_by: arguments in this kwarg are sent to the QuerySet order_by method
        qs_select_rel: arguments in this kwarg are sent to the QuerySet select_related method
        qs_prefetch_rel: arguments in this kwarg are sent to the QuerySet prefetch_related method

        qs_auto_select: True to select all ForeignKey fields during initial query
        qs_auto_prefetch: True to prefetch all ManyToMany fields during initial query

        qs_prefetch_select: True to automatically return (select) Foreign key fields from the prefetched object

        qf__(field_name): allows comparisons to data within the same object
        (field_name)__ex: allow exclusion of fields-- like filtering fields, but the reverse
        """
        qs = cls.filter(*args, **kwargs)
        # just use the filter for all the additional logic
        return qs.first() if qs else None

    @classmethod
    def by_id(cls, *args, **kwargs) -> Optional['BaseModel']:
        """
        Simple get method - excludes inheritance
        Supports the same kwargs as ez_filter
        """
        obj = cls.get(*args, **kwargs)
        # just use the filter for all the additional logic
        return getattr(obj, 'id') if obj else None

    @staticmethod
    def parse_f_kwargs(kwargs: dict):
        """
        Excluded arguments are parsed from "{field_name}__ex" kwargs
        F object references are indicated by prepending qf__ to the field names
        (F objects allow us to compare two fields in the database during the query)
        """
        from django.db.models import F
        exclude = {}
        for k, v in kwargs.items():
            if type(v) is str:
                if v.startswith('qf__'):
                    v = F(str(v).replace('qf__', ''))
                    kwargs[k] = v
            if str(k).endswith('__ex'):
                exclude[str(k).replace('__ex', '')] = v
        for k in exclude.keys():
            kwargs.pop(f'{k}__ex')
        return exclude

    @classmethod
    def foreign_key_field_list(cls) -> List[models.ForeignKey]:
        return [field for field in cls.get_meta().fields if field.get_internal_type() == 'ForeignKey']

    @classmethod
    def many_to_many_field_list(cls) -> List[models.ManyToManyField]:
        return [field for field in cls.get_meta().many_to_many]

    @classmethod
    def get_prefetch_select(cls, pre_rel):
        """
        Used to automatically generate select_related arguments from a list of m2m fields
        """
        pre_temp = []
        for rel in pre_rel:
            if type(rel) is str:
                for f in cls.many_to_many_field_list():
                    if f.name == rel:
                        pre_temp.append(cls.return_prefetch_object(f))
            else:
                pre_temp.append(rel)
        return pre_temp

    @staticmethod
    def return_prefetch_object(m2m_field):
        """
        For automatically selecting foreignkey fields during a prefetch_related
        """
        from django.db.models import Prefetch
        many_sel = []
        m2m_model = m2m_field.related_model
        for fld in m2m_model.foreign_key_field_list():
            if not fld.related_model == m2m_field.model:  # in many cases, this is just the cross-reference
                many_sel.append(fld.name)
        if many_sel:
            return Prefetch(m2m_field.name, queryset=m2m_model.objects.select_related(*many_sel))
        else:
            return m2m_field.name

    @classmethod
    def filter(cls, *args, **kwargs) -> QuerySet:
        """
        Simple filter method - excludes inheritance

        available kwargs:
        qs_order_by: arguments in this kwarg are sent to the QuerySet order_by method
        qs_select_rel: arguments in this kwarg are sent to the QuerySet select_related method
        qs_prefetch_rel: arguments in this kwarg are sent to the QuerySet prefetch_related method

        qs_auto_select: True to select all ForeignKey fields during initial query
        qs_auto_prefetch: True to prefetch all ManyToMany fields during initial query

        qs_prefetch_select: True to automatically return (select) Foreign key fields from the prefetched object

        qf__(field_name): allows comparisons to data within the same object
        (field_name)__ex: allow exclusion of fields-- like filtering fields, but the reverse
        """
        order = None
        sel_rel = None
        pre_rel = None
        prefetch_select = False

        # Kwargs are processed below...
        if kwargs.get('qs_prefetch_select'):
            prefetch_select = kwargs.pop('qs_prefetch_select')
        if kwargs.get('qs_order_by'):
            order = kwargs.pop('qs_order_by')
        if kwargs.get('qs_select_rel'):
            sel_rel = kwargs.pop('qs_select_rel')
        if kwargs.get('qs_prefetch_rel'):
            pre_rel = kwargs.pop('qs_prefetch_rel')
        if kwargs.get('qs_auto_select'):
            # automatically get all the foreign key fields and return the related objects
            if kwargs.pop('qs_auto_select'):
                if not sel_rel:
                    sel_rel = []
                for f in cls.foreign_key_field_list():
                    sel_rel.append(f.name)
        if kwargs.get('qs_auto_prefetch'):
            # automatically prefetch m2m field list data--
            #   if prefetch_select is specified, the related foreign key fields for each prefetched object
            #   is also returned
            if kwargs.pop('qs_auto_prefetch'):
                if not pre_rel:
                    pre_rel = []
                for f in cls.many_to_many_field_list():
                    if prefetch_select:
                        pre_rel.append(cls.return_prefetch_object(f))
                    else:
                        pre_rel.append(f.name)

        # excluded arguments are parsed from "{field_name}__ex" kwargs
        # f objects are added to the kwargs here
        exclude = cls.parse_f_kwargs(kwargs)

        # build the base query
        qs = cls.objects.filter(*args, **kwargs)

        if exclude:
            # if we have "exclude" options...
            qs = qs.exclude(**exclude)

        if order:
            # when we've been told to order the results... takes a list, a tuple, or a single string
            if type(order) is list or type(order) is tuple:
                qs = qs.order_by(*order)
            else:
                qs = qs.order_by(order)

        if sel_rel:
            # select related data for foreign key fields...
            qs = qs.select_related(*sel_rel)

        if pre_rel:
            # prefetch list data for m2m fields...
            if prefetch_select:
                # during prefetch, select related foreign key fields
                pre_rel = cls.get_prefetch_select(pre_rel)
            qs = qs.prefetch_related(*pre_rel)

        # ...aaaand, the QuerySet object is returned
        return qs

    @classmethod
    def ez_obj(cls, obj_or_id: Union[Type['BaseModel'], int, str, None]) -> (Optional['BaseModel'], int):
        """
        Ensures that we have an object instance
        """
        if type(obj_or_id) is str or type(obj_or_id) is int:
            this_obj = cls.get(id=obj_or_id)
        else:
            this_obj = obj_or_id
        return this_obj, int(this_obj.id if this_obj else obj_or_id)

    @classmethod
    def get_content_type(cls) -> Optional[ContentType]:
        """
        Get the content type object for this class
        :return: the Django Content Type Instance for this model
        """
        from utils import ModelUtil
        return ModelUtil.get_content_type(cls)

    @staticmethod
    def many_to_csv(m2m_field):
        """
        Used to return a comma-separated value of ids for the specified many-to-many field
        :param m2m_field: the Model's Field Object. (model.m2m_prop)
        :return: ID CSV list
        """
        id_list = [str(obj.id) for obj in m2m_field.all()]
        return ",".join(id_list) if id_list else ""

    @classmethod
    def wsrep_retry(cls, ex, f, *args, **kwargs):
        wsrep_retry_count = kwargs.pop('wsrep_retry_count', 0)
        wsrep_autolog = kwargs.pop('wsrep_autolog', True)

        if 'wsrep' in str(repr(ex)).lower():
            from time import sleep
            sleep(5)
            try:
                return f(*args, **kwargs)
            except Exception as ex:
                if wsrep_retry_count < 10:
                    kwargs['wsrep_retry_count'] = wsrep_retry_count + 1
                    return cls.wsrep_retry(ex, f, *args, **kwargs)
                if wsrep_autolog:
                    try:
                        from core.models import Log
                        Log.crit("Query Failed: (Retry count exceeded!)", ex=ex)
                    except:
                        print("Retry count exceeded! Logging failed.")
                raise ex
        else:
            if wsrep_autolog:
                try:
                    from core.models import Log
                    Log.crit("Query failed: (No retry Performed!)", ex=ex)
                except:
                    print("No retry Performed! Logging failed.")
            raise ex  # now only logging in core.Log

    @classmethod
    def generate_choices(cls):
        all_fields = cls.get_meta().fields

        choices = {}
        for field in all_fields:
            if field.remote_field:
                f_name = str(field.remote_field.model.__name__).lower()
                if f_name not in choices.keys():
                    choices[f_name] = []
                    for obj in field.remote_field.model.objects.all():
                        choices[f_name].append(obj)
        return choices

    @classmethod
    def get_fields(cls, m2m=True):
        # model._meta.get_fields() returns ManyToManyRel -- which is not always ideal
        meta = cls.get_meta()
        return meta.fields + meta.many_to_many if m2m else meta.fields

    def validate_field(self, field_name):
        """
        Make sure the field does not hold an invalid record.
        It's a good idea to prefetch fields you wish to validate.
        :param field_name: string of the property we are checking
        :return: True/False (the data could be assigned to an object)
        """
        try:
            if hasattr(self, field_name):
                obj = getattr(self, field_name)
                if obj is not None:
                    # print(obj.id)
                    return True
        except Exception as ex:
            return None
        return False

    # @classmethod
    # def generate_list_view_columns(cls):
    #     """
    #     Used to generate columns for the list view from the model definition values
    #     :return: ColumnDefs object
    #     """
    #     from core.util import generate_list_view_columns
    #     return generate_list_view_columns(cls)

    # @classmethod
    # def save_or_create_model_xref(cls, r_source_obj, soc_ext_source_key, soc_filter_dict: dict = None,
    #                               soc_user=None, soc_update=True, org_id=None, **kwargs):
    #     """
    #     Saves or creates a new model object based upon the xref information provided
    #     :param r_source_obj: The name of the external source-- must match existing RecordSource value
    #     :param soc_ext_source_key: The external key value to associate with the current record
    #     :param soc_filter_dict: takes a dictionary keyed by the field name/filter method and the value to filter by
    #     :param soc_update: optionally skip record updates
    #     :param soc_user: user is optional. Triggers logging of changes.
    #     :param kwargs: fieldname=value -- the fields to update in the model
    #     :param org_id:
    #     :return: model object, updated/created boolean value, before data-- as a tuple
    #     """
    #     model_object = None
    #     updated = False
    #     pre_data = None
    #     try:
    #         xr = cls.get_model_xref(r_source_obj, soc_ext_source_key, org_id=org_id)
    #         if not xr or not xr.instance:
    #             if soc_filter_dict:
    #                 model_object, updated, pre_data = cls.save_or_create_model(
    #                     soc_filter_dict, soc_user, soc_update, **kwargs)
    #             else:  # when the filter_dict isn't specified, we are using the xref as the unique key for these records
    #                 model_object = cls.create_model(soc_user, **kwargs)
    #                 updated = True
    #             xr = model_object.make_model_xref(r_source_obj, soc_ext_source_key)
    #         elif soc_update:
    #             model_object = xr.instance
    #             updated, pre_data = model_object.save_model(soc_user, **kwargs)
    #         return xr, model_object, updated, pre_data
    #     except Exception as ex:
    #         return cls.wsrep_retry(ex, cls.save_or_create_model_xref,
    #                                r_source_obj, soc_ext_source_key, soc_filter_dict, soc_user, soc_update, **kwargs)

    @classmethod
    def clean_kwargs(cls, user_object=None, creating: bool = False, kwargs: dict = None):
        """
        Intended to be used by the save_model and create_model methods
        :param user_object: the django user object for the user who is saving the model
        :param creating: whether a new model will be created
        :param kwargs: the field values to be saved
        :return: returns the parsed kwarg dictionary sans the "_id" field values
        """
        if not kwargs:
            kwargs = {}
        if creating:
            # forces the organization and division fields to be filled out
            # if user_object and hasattr(cls, 'organization') and \
            #         'organization' not in kwargs and 'organization_id' not in kwargs:
            #     kwargs['organization_id'] = user_object.selected_org_id
            if user_object and hasattr(cls, 'created_user') and 'created_user' not in kwargs:
                kwargs['created_user'] = user_object

        if user_object and hasattr(cls, 'last_user') and 'last_user' not in kwargs:
            kwargs['last_user'] = user_object

        for k, v in kwargs.items():
            if str(k).endswith('_id') and v == -1:
                # value was deselected
                kwargs[k] = None

        return kwargs

    @classmethod
    def model_field_exists(cls, field):
        return cls.field_exists(field)

    @classmethod
    def create_model(cls, magic_user_object=None, **kwargs):
        """
        combines logging functionality with model record creation
        :param magic_user_object: The core.User object
        :param kwargs: These arguments are passed directly to the objects.create method
        :return: the model instance
        """
        from utils import DateUtil, ModelUtil
        kwargs = cls.clean_kwargs(agile_user_object, True, kwargs)

        log_org = kwargs.pop('log_org', None)

        wsrep_autolog = kwargs.pop('wsrep_autolog', True)

        additional_log_text = kwargs.pop('magic_log_text', '')

        m2m = {}
        for field in cls.get_meta().many_to_many:
            if field.name in kwargs:
                if str(kwargs[field.name]) == '-1':
                    m2m[field.name] = []
                else:
                    m2m[field.name] = [ModelUtil.obj_int_if_possible(i) for i in str(kwargs[field.name]).split(",")]
                kwargs.pop(field.name)

        if kwargs:
            try:
                cls.save_submodels(agile_user_object, kwargs)
            except Exception as ex:
                kwargs['wsrep_autolog'] = wsrep_autolog
                cls.wsrep_retry(ex, cls.save_submodels, magic_user_object, **kwargs)

        try:
            if cls.field_exists('created') and 'created' not in kwargs.keys():
                kwargs['created'] = DateUtil.now()
            if cls.field_exists('updated') and 'updated' not in kwargs.keys():
                kwargs['updated'] = DateUtil.now()
            obj = cls.objects.create(**kwargs)
        except Exception as ex:
            kwargs['wsrep_autolog'] = wsrep_autolog
            obj = cls.wsrep_retry(ex, cls.objects.create, **kwargs)

        # blank out all the initial fields
        obj.init_fields(True)

        if m2m:
            try:
                obj.m2m_update(m2m, None)
            except Exception as ex:
                cls.wsrep_retry(ex, obj.m2m_update, m2m, None, **{'wsrep_autolog': wsrep_autolog})

        # if not log_org:
        #     obj.log_org_checker(kwargs, log_org, magic_user_object)
        obj.save_field_history(agile_user_object, log_org)
        if magic_user_object:
            obj.log_model_create(
                magic_user_object,
                f"{cls.__name__} record was created by User: {agile_user_object.username}. "
                f"{f'({additional_log_text})' if additional_log_text else ''}",
                "CREATED",
                org=log_org)
        return obj

    # @classmethod
    # def get_view_list_qs(cls, org=None):
    #     """
    #     Get the QuerySet (list view mode) for this model while automatically applying filters
    #     for "Active" status as well as organization
    #     :param org: organization to select. None or undefined is all.
    #     :return: QuerySet object
    #     """
    #     qs = cls.org_qs(org)
    #     if cls.field_exists('active'):
    #         qs = qs.filter(active=True)
    #     return qs

    @classmethod
    def field_exists(cls, field_name):
        """
        Check for a field in this current model
        """
        from django.core.exceptions import FieldDoesNotExist
        try:
            f = cls.get_meta().get_field(field_name)
        except FieldDoesNotExist:
            f = None
        if f:
            return True
        elif field_name.endswith("_id"):
            return cls.field_exists(field_name[:str(field_name).index("_id")])
        return False

    # @classmethod
    # def get_view_qs(cls, org=None, filter_q=None):
    #     """
    #     Get the QuerySet for this model while automatically applying filters
    #     :param org: organization to select. None or undefined is all.
    #     :param filter_q:
    #     :return:
    #     """
    #     qs = cls.org_qs(org)
    #     if filter_q:
    #         qs = qs.filter(filter_q)
    #
    #     if cls.field_exists('active'):
    #         qs = qs.filter(active=True)
    #
    #     # this was added before org inheritance was a thing...
    #     # if not qs and cls.organization_fallback():
    #     #     org = cls.get_org(org)
    #     #     if not org or not org.root_org:
    #     #         # the root organization is not forced to view only their own records while others are.
    #     #         from core.models import Organization
    #     #         org = Organization.get_root()
    #     #         return cls.get_view_qs(org, filter_q)
    #     return qs

    @classmethod
    def save_submodels(cls, user, kwargs):
        """
        currently only supports creating new sub-models and adding initial attributes,
        but not modifying attributes
        :param user: the user object
        :param kwargs: field properties and values in a dictionary
        :return: Nothing
        """
        new_models = {}
        pop_list = []

        all_fields = cls.get_fields(False)
        for k, v in kwargs.items():
            if '__' in k:
                sp = str(k).split('__')
                for field in all_fields:
                    if sp[0] == field.name:
                        rel_model = field.related_model
                        model_id = "{0}_id".format(sp[0])
                        this_attr = str(k).replace("{0}__".format(sp[0]), '')
                        if type(field) is models.ForeignKey or type(field) is models.OneToOneField:
                            if model_id not in kwargs:
                                # the id was not given-- so we will create a new record for this
                                new_models[field.name] = {"model_id": model_id, this_attr: v, 'model': rel_model}
                            else:
                                new_models[field.name] = {"edit_id": model_id, this_attr: v, 'model': rel_model}
                        elif field.name in new_models:
                            new_models[field.name][this_attr] = v
                        pop_list.append(k)
                        break
        if pop_list:
            for kw in pop_list:
                kwargs.pop(kw)
        if new_models:  # create new model references/update models
            for field_name, attributes in new_models.items():
                model = attributes['model']
                attr = attributes.copy()
                attr.pop('model')
                if 'edit_id' not in attributes:  # creating a new reference
                    model_id = attributes['model_id']
                    attr.pop('model_id')
                    nm = model.create_model(user, **attr)
                    if nm:
                        kwargs[model_id] = nm.id
                else:
                    model_id = attributes['edit_id']
                    attr.pop('edit_id')
                    instance = model.get_model(kwargs[model_id])
                    instance.save_model(user, **attr)

    @classmethod
    def set_bulk(cls, id_list, update_vals: dict, user=None):
        """
        Used to update many records for a model in one go
        """
        from django.db import transaction
        from core.models import Log
        obj_list = cls.filter(id__in=id_list)

        try:
            with transaction.atomic:
                for obj in obj_list:
                    obj: BaseModel
                    obj.save_model(user, **update_vals)
            print(f"{len(obj_list)} records updated. ({str(update_vals)})", True)
        except Exception as ex:
            Log.error(f"Failed to bulk update IDs: {str(id_list)} values:{str(update_vals)}", ex=ex)

    @classmethod
    def set_bulk_targeted(cls, dict_vals: dict):
        """
        Used to update many specific model records with various changes in one go
        """
        from django.db import transaction
        from core.models import Log
        assert dict_vals is type(dict)
        addr_list = cls.filter(id__in=dict_vals.keys())
        try:
            with transaction.atomic:
                for addr in addr_list:
                    addr.save_model(**dict_vals[addr.id])
            print(f"Applied {len(dict_vals.keys())} bulk changes!", True)
        except Exception as ex:
            Log.error(f"Failed to bulk update IDs: [{str(dict_vals.keys())}] "
                      f"values: [{str(dict_vals.values())}]", ex=ex)

    def model_differences(self, change_dict: dict):
        upd_obj = {}
        for k in change_dict.keys():
            if hasattr(self, k):
                if getattr(self, k) != change_dict[k]:
                    upd_obj[k] = change_dict[k]
            elif hasattr(self, f"{k}_id"):
                if str(change_dict[k]).isnumeric():
                    upd_obj[f"{k}_id"] = int(change_dict[k])
                elif hasattr(change_dict[k], 'id'):
                    upd_obj[f"{k}_id"] = getattr(change_dict[k], 'id')
        return upd_obj

    def save_model(self, user=None, enforce_updated=False, **kwargs):
        """
        Parses the fields to be updated and compares values with current model values -- only saves changed values
        :param user: The core.User object
        :param enforce_updated: set the updated date if none is given (default: False)
        :param kwargs: These arguments are passed directly to the objects.save() method
        :return: tuple of True/False, cached data (for possible reversion)
        """
        import json
        from core.templatetags.custom_fields import csv as csv_parse
        from core.util import merge_dict
        m2m = {}
        pre_data = {}  # cache data before the save
        pre_m2m = {}
        initial_kwargs = kwargs.copy()
        dup_clear = False
        if 'magic_duplicate_clear' in kwargs:
            dup_clear = kwargs.pop('magic_duplicate_clear')
        save_org_check = False
        if 'save_org_check' in kwargs:
            save_org_check = kwargs.pop('save_org_check')

        other_kwargs = kwargs.pop('other_kwargs', None)

        log_org = None
        if 'log_org' in kwargs:
            log_org = kwargs.pop('log_org')

        # if the last_user arg is not populated, also remove unnecessary fields
        kwargs = self.clean_kwargs(user, kwargs=kwargs)

        if save_org_check:
            if hasattr(self, 'organization') and 'organization' not in kwargs and 'organization_id' not in kwargs:
                kwargs['organization_id'] = self.required_org(user, None)
                if not kwargs['organization_id']:
                    # from django.conf import settings as dj_cfg
                    kwargs['organization_id'] = dj_cfg.DEFAULT_ORG_ID

        for field in self.get_meta().many_to_many:
            if field.name in kwargs:
                if str(kwargs[field.name]) == '-1':
                    m2m[field.name] = []
                else:
                    m2m[field.name] = [int(i) for i in str(kwargs[field.name]).split(",")]
                kwargs.pop(field.name)
                pre_m2m[field.name] = csv_parse(getattr(self, field.name).all(), 'id')

        if kwargs:
            try:
                self.save_submodels(user, kwargs)
            except OperationalError as ex:
                self.wsrep_retry(ex, self.save_submodels, user, kwargs)

        for k, v in kwargs.items():
            pre_val = getattr(self, k)
            if not pre_val == v:
                pre_data[k] = pre_val
                setattr(self, k, v)

        self.save_field_history(user, log_org)

        if len(pre_data.keys()) > 0:
            from django.db.utils import IntegrityError
            if enforce_updated and self.field_exists('updated') and 'updated' not in pre_data.keys():
                pre_data['updated'] = tz.now()
            try:
                if other_kwargs and type(other_kwargs) is dict:
                    other_kwargs['update_fields'] = list(pre_data.keys())
                    self.save(**other_kwargs)
                else:
                    self.save(update_fields=list(pre_data.keys()))
            except OperationalError as ex:
                self.wsrep_retry(ex, self.save, update_fields=list(pre_data.keys()))
            except IntegrityError as ex:
                if 'Duplicate entry' in repr(ex):
                    if dup_clear:
                        dup_record = self.dup_check(self)
                        if dup_record:
                            dup_record.delete()
                            self.save_model(user, **initial_kwargs)  # duplicate has been cleared... now try again...
                        else:
                            raise IntegrityError(
                                "Failed to clear duplicate entry.") from ex
                    else:
                        raise IntegrityError("Unique index check would be violated if we were to save this.") from ex
                else:
                    raise IntegrityError("Unknown failure to save model changes.") from ex

            changed_m2m = self.m2m_update(m2m, pre_m2m)

            if user:
                self.log_model_update(user,
                                      "{0} record was updated by user:{1}. Updated fields: {2}"
                                      "".format(self.__class__.__name__, user.username,
                                                json.dumps(list(list(pre_data.keys()) + list(pre_m2m.keys())))),
                                      "UPDATED")
            return True, merge_dict(pre_data, changed_m2m)
        elif len(m2m.keys()) > 0 or pre_m2m:
            changed_m2m = self.m2m_update(m2m, pre_m2m)
            if user:
                self.log_model_update(user,
                                      "{0} record was updated by user:{1}. Updated fields: {2}"
                                      "".format(self.__class__.__name__, user.username,
                                                json.dumps(list(pre_m2m.keys()))), "UPDATED")
            return True, changed_m2m
        else:
            return False, None

    @classmethod
    def get_verbose_name(cls, field_name):
        """
        Get the verbose name for a model field definition if it exists.
        :param field_name: field property string
        :return: String representation for the field
        """
        field = cls.get_meta().get_field(field_name)
        if field:
            return field.verbose_name.title() if hasattr(field, 'verbose_name') else f'Field: "{field_name}"'
        else:
            return f"Invalid Field ({field_name})!"

    @classmethod
    def meta(cls, meta_attr, default=None):
        """
        Retrieve meta class attributes
        :param meta_attr: the meta attribute name
        :param default: the default value to be returned for the given attribute
        :return: the attribute value
        """
        return getattr(cls.get_meta(), meta_attr, default)

    class Meta:
        abstract = True
        base_manager_name = 'objects'
        #
        # """
        # These are custom meta attributes -- moved here to reduce the likelihood of duplicate attributes
        # """
        # ag_celery_interval = False  # set whether this model will run the interval code
        # ag_unique_default = 'value'  # this is the name of the field used to determine uniqueness by default
        #
        # # admin/view generation stuff
        # ag_show_admin = False
        # ag_manual_admin_views = False
        # ag_url_section = None
        # ag_css_icon = None
        # ag_order_by = None  # meant for a date or sequential id
        # ag_name_attr = None  # defaults to 'name'
        # ag_name_attr_is_method = False  # if the name attribute is not a property
        # ag_date_attr = None  # defaults to 'created'
        # ag_view_permission = None  # required for generating admin views
        # ag_edit_permission = None
        # ag_create_permission = None
        # ag_remove_permission = None
        # ag_admin_tab = 'core'  # default to core, cause why not
        # ag_org_fallback = True  # defaulting to fallback (for models that implement the organization field)
        # ag_editor_template = 'core/admin/generic/undefined.html'
        # verbose_name = 'Unknown Model'
        # verbose_name_plural = "UknwnMdls"


class ProvideDefaultDataModel(BaseModel):

    @staticmethod
    def get_default_models():
        """
        you can define default model instances for each class -- these will not be created unless none exist
        USES unique_default
        :return: type: list
        """
        definitions = [
            # {'name': 'Web', 'value': '1', 'tooltip': 'Submitted via web form.', 'color': None,
            # 'icon_class': None, 'order': 0}
        ]
        return definitions

    @classmethod
    def initialize_default_records(cls, reinit_value=False, explicit: Optional[dict] = None):
        init_objs = cls.get_default_models()
        if init_objs:
            print('Verifying default values exist for {0}...'.format(cls.__name__))
            for i in init_objs:

                # used to pass values that always get sent (ex: organization, group, etc)
                if type(explicit) is dict:
                    for key, val in explicit:
                        if hasattr(cls, key):
                            i[key] = val

                unique_eval = cls.get_unique_eval(i)
                if unique_eval:
                    print(f"Checking for uniqueness ({str(i)})....")
                    qs = cls.objects.filter(**unique_eval)
                    if not qs.exists():
                        cls.objects.create(**i)
                        if 'value' in i:
                            print(f"Created {i['value']} ORG: {i.get('organization_id', 'N/A')}")
                        else:
                            print('Created {0}'.format(str(i)))
                    elif reinit_value:
                        if 'name' in i:
                            print("Restoring record default values.")
                            # only updates records with a name field-- which is untouched
                            obj = qs.first() if qs else None
                            if obj:
                                i_vals = i.copy()
                                i_vals.pop('name')
                                obj.save_model(**i_vals)
                                if 'value' in i:
                                    print('Updated {0}'.format(i['value']))
                                else:
                                    print('Updated {0}'.format(str(i)))
                    else:
                        print("Already exists. Skipped.")

    class Meta:
        abstract = True

class HistoryMixin(models.Model):
    def get_model_change_log(self, start: tz.datetime = None, end: tz.datetime = None,
                             update_type=None) -> models.query.QuerySet:
        """
        Get the change log for this record
        :param start: start date
        :param end: end date
        :param update_type: the update type id
        :return: QuerySet containing ChangeHistory objects
        """
        return self.get_change_log(start, end, update_type, [{'ct': self.get_content_type(), 'key': self.pk}])

    @classmethod
    def get_change_log(cls, start: datetime = None, end: datetime = None, update_type=None,
                       content_type_list=None, user=None, user_level=True,
                       org_limit=None, org=None) -> models.query.QuerySet:
        """
        Get the change log for this model
        :param start: start date
        :param end: end date
        :param update_type: the update type id
        :param content_type_list: for the option to include multiple content types in the query -
          can be list of content types or a list of dictionaries as {ct: type, key: my_key}
        :param user: core.User instance used for limiting data
        :param user_level: True/False limit the query to the user's data,
          otherwise inside the organization/division.
          When user is not specified, all data is returned
        :param org_limit: list of orgs to return data for
        :param org: UNUSED - will eventually be refactored
        :return: QuerySet containing ChangeHistory objects
        """
        from core.models import ChangeHistory, QSFilter, Q
        if content_type_list:
            qs_f = None
            if type(content_type_list[0]) is dict:
                for ct in content_type_list:
                    if not qs_f:
                        qs_f = QSFilter((Q(content_type=ct['ct']) & Q(key=ct['key'])))
                    else:
                        qs_f.x_or((Q(content_type=ct['ct']) & Q(key=ct['key'])))
            else:  # we assume that if it's not a dictionary, it's a ContentType
                qs_f = QSFilter(Q(content_type=cls.get_content_type()))
                for ct in content_type_list:
                    qs_f.x_or(Q(content_type=ct))
        else:
            qs_f = QSFilter(Q(content_type=cls.get_content_type()))

        if user:
            if user_level:
                qs_f.grp_and(Q(user=user))

        if org_limit:
            qs_f.grp_and(Q(user__organization_list__in=org_limit))

        if update_type:
            qs_f.grp_and(Q(type=update_type))

        if start and end:
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = end.replace(hour=0, minute=0, second=0, microsecond=0) + tz.timedelta(days=1)
            qs_f.grp_and(Q(created__gte=start) & Q(created__lt=end))

        # org = ChangeHistory.required_org(user, org)
        # qs = ChangeHistory.org_qs(org)
        return ChangeHistory.filter(qs_f.filter)

    def get_model_access_log(self) -> models.query.QuerySet:
        """
        Get the access log for an instance
        :return: QuerySet containing AccessHistory objects
        """
        from core.models import AccessHistory
        return AccessHistory.get_history(self.get_content_type().model_class(), None, None, self.pk)

    def log_model_access_req(self, request):
        org_id = BaseModel.request_org(request)
        return self.log_model_access(request.user, org_id)

    def log_model_access(self, user, org=None):
        """
        Run when you want to track the user's access of the record
        :param user: core.User instance
        :param org: the organization id
        :return: AccessHistory object
        """
        from core.models import AccessHistory

        org = self.required_org(user, org)
        try:
            return AccessHistory.objects.create(content_type=self.get_content_type(), key=self.pk,
                                                user=user, organization_id=org)
        except Exception as ex:
            return self.wsrep_retry(ex, self.log_model_access, user)

    def log_model_change(self, user, detail, change_type, code=None, org=None):
        """
        Run when you want to track when values are changed in a model instance
        :param user: core.User instance
        :param detail: a text description of the change-- meant to be displayed to the user
        :param change_type: the change type id (ChangeHistory.CHANGE_TYPES)
        :param code: a code-- for use in quickly identifying subsets of changes
        :return: ChangeHistory object
        """
        from core.models import ChangeHistory
        org = self.required_org(user, org, self)

        if not code:
            code = "GENERAL"
        try:
            return ChangeHistory.objects.create(content_type=self.get_content_type(), key=self.pk, user=user,
                                                type=change_type, detail=detail, code=code, organization_id=org)
        except Exception as ex:
            return self.wsrep_retry(ex, self.log_model_change, user, detail, change_type, code, org)

    def log_model_update(self, user, detail, code=None, org=None):
        """
        Log when a model is updated
        :param user: core.User instance
        :param detail: a text description of the change-- meant to be displayed to the user
        :param code: a code-- for use in quickly identifying subsets of changes
        :return: ChangeHistory object
        """
        from core.models import ChangeHistory
        return self.log_model_change(user, detail, ChangeHistory.TYPE_UPDATED, code, org)

    def log_model_create(self, user, detail, code=None, org=None):
        """
        Log when a model is created
        :param user: core.User instance
        :param detail: a text description of the change-- meant to be displayed to the user
        :param code: a code-- for use in quickly identifying subsets of changes
        :return: ChangeHistory object
        """
        from core.models import ChangeHistory
        return self.log_model_change(user, detail, ChangeHistory.TYPE_CREATED, code, org)

    def log_model_delete(self, user, detail, code=None, org=None):
        """
        Log when a model is "deleted"
        :param user: core.User instance
        :param detail: a text description of the change-- meant to be displayed to the user
        :param code: a code-- for use in quickly identifying subsets of changes
        :return: ChangeHistory object
        """
        from core.models import ChangeHistory
        return self.log_model_change(user, detail, ChangeHistory.TYPE_DELETED, code, org)

    def clear_model_history(self):
        """
        meant to be performed before a model instance is permanently removed.
        :return: None
        """
        from core.models import ChangeHistory, AccessHistory
        ChangeHistory.objects.filter(content_type=self.get_content_type(), key=self.pk).delete()
        AccessHistory.objects.filter(content_type=self.get_content_type(), key=self.pk).delete()


class RecordStatusMixin(models.Model):
    def set_model_status(self, user, status):
        from core.models import StatusType
        if hasattr(self, 'status') and type(self.status) is StatusType:
            if type(status) is str and (status in StatusType.get_possible_values()):
                self.status = StatusType.get_model_val(status)
                self.save(update_fields=['status'])
            elif type(status) is StatusType:
                self.status = status
                self.save(update_fields=['status'])
            else:
                raise (Exception('set_model_status: status parameter is invalid! Requires value or StatusType.'))
            if user:
                self.log_model_delete(user, 'Record was removed from deletion queue.', 'DEL_QUEUE_REM')
        else:
            raise (Exception('Model must have a status field defined to set status.'))

    def delete_model(self, user=None, hard_delete=False, deactivate=False):
        from core.models import StatusType
        done = True
        if hard_delete:
            self.delete()
        elif hasattr(self, 'status') and type(self.status) is StatusType:
            if not self.status.value == 'a':
                self.set_model_status(user, 'a')
                done = False
            else:
                if deactivate:
                    self.set_model_status(user, 'i')
                else:
                    self.set_model_status(user, 'd')

        elif hasattr(self, 'active') and type(getattr(self, 'active')) is bool:
            if getattr(self, 'active'):
                setattr(self, 'active', False)
            else:
                setattr(self, 'active', True)
                done = False
            self.save(update_fields=['active'])
        else:
            raise (Exception('Model must have a status or active field defined or else a hard delete is required.'))

        return done

    @classmethod
    def purge_deleted(cls):
        """
        Permanently deletes records that have been marked for Deletion
        """
        from core.models import StatusType
        obj = cls.objects.all().first()
        if obj and hasattr(cls, 'status') and type(obj.status) is StatusType:
            for r in cls.objects.filter(status__value='d'):
                r.delete()

    class Meta:
        abstract = True


class BackendProcessMixin(models.Model):
    @classmethod
    def minutely_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every minute
        :return: None
        """
        return

    @classmethod
    def hourly_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every hour
        (*) runs with minutely processes... technically
        :return: None
        """
        return

    @classmethod
    def daily_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every day (beginning)
        (*) runs with minutely processes
        :return: None
        """
        return

    @classmethod
    def weekly_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every week (beginning)
        (*) runs with daily processes
        :return: None
        """
        return

    @classmethod
    def monthly_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every month (beginning)
        (*) runs with daily processes
        :return: None
        """
        return

    @classmethod
    def quarterly_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every quarter (beginning)
        (*) runs with daily processes
        :return: None
        """
        return

    @classmethod
    def yearly_process(cls, org_obj):
        """
        If magic_celery_interval is True and the celery worker and beat are running, runs every year (beginning)
        (*) runs with daily processes
        :return: None
        """
        return

    class Meta:
        abstract = True


class TrackableMixin(models.Model):

    @staticmethod
    def watch_fields() -> List[str]:
        """
        Specify a list of fields to watch for changes.
        MUST BE SET ON THE MODEL LEVEL
        :return: the list of field names.
        """
        return []

    def init_fields(self, blank=False):
        """
        Save the field values from the watch field list from this point on.
        Set blank to initialize all field values as None.
        """
        wf = self.watch_fields()
        if not wf:
            return
        for field in wf:
            if not blank:
                setattr(self, f"__init_{field}", getattr(self, field))
            else:
                setattr(self, f"__init_{field}", None)

    def has_changed(self) -> Optional[Dict]:
        """
        Check for changes and return the fields with changes including old and new values
        This is good for logging. For retrieving the save list, use tracked_changes.
        :return: dictionary or none
        """
        wf = self.watch_fields()
        if not wf:
            return None
        changes = {}
        for field in wf:
            init = f"__init_{field}"
            if hasattr(self, init) and hasattr(self, field):
                before_val = getattr(self, init)
                after_val = getattr(self, field)
                if before_val != after_val:
                    changes[field] = {'old': before_val, 'new': after_val}
        return changes

    def tracked_changes(self) -> Dict:
        """
        Retrieves a dictionary that can be fed to save_model.
        """
        changes = self.has_changed()
        change_dict = {}
        for k, d in changes:
            change_dict[k] = d['new']
        return change_dict

    class Meta:
        abstract = True


class MagicFlagMixin(models.Model):
    def load_task_flags(self):
        from core.models import TaskFlag
        self.__task_flags = {}
        self.__task_flag_objs = {}
        if self.id:
            flags = TaskFlag.filter(content_type_id=self.get_content_type().id, record_id=self.id)
            for flag in flags:
                self.__task_flags[flag.flag] = flag.value
                self.__task_flag_objs[flag.flag] = flag

    def __change_cached_flag(self, flag, flag_obj):
        """
        update the dictionary stored on the object
        """
        if self.__task_flags is None:
            self.load_task_flags()
        if flag_obj:
            self.__task_flags[flag] = flag_obj.value
            self.__task_flag_objs[flag] = flag_obj
        else:
            if self.__task_flags.get(flag) is not None:
                self.__task_flags.pop(flag)
                self.__task_flag_objs.pop(flag)

    @classmethod
    def has_flag(cls, org_id, flag) -> QuerySet:
        """
        Return whether a flag is associated with a particular model
        @param org_id: the organization
        @param flag: the flag
        @return: QuerySet of Model objects that meet the criteria
        """
        from core.models import TaskFlag
        return cls.ez_filter(
            organization_id=org_id, id__in=TaskFlag.filter(
                content_type_id=cls.get_content_type().id,
                flag=flag).values_list('record_id', flat=True))

    @classmethod
    def org_qs_has_flag(cls, org_id, flag) -> QuerySet:
        """
        Return whether a flag is associated with a particular model
        @param org_id: the organization
        @param flag: the flag
        @return: QuerySet of Model objects that meet the criteria
        """
        from core.models import TaskFlag
        return cls.get_view_list_qs(org_id).filter(id__in=TaskFlag.filter(
                content_type_id=cls.get_content_type().id,
                flag=flag).values_list('record_id', flat=True))

    @staticmethod
    def get_app_models(app_name) -> iter:
        """
        Get all current models for a Django app

        Wrap this method in a try block

        Raises LookupError if no application exists with this label.
        @param app_name: core, dispatch, support, etc
        @return: All models for a given django app as iter
        """
        from django.apps import apps
        app_cfg = apps.get_app_config(app_name)
        return app_cfg.get_models()

    def get_flag(self, flag: str, force_query=False) -> Optional['BaseModel']:
        """
        Return the flag instance for this record

        :param: flag: is a flag name - essentially the key for the flag
        :param: force_query: True/False to perform a query ignoring the cached values
        :return: TaskFlag object instance
        """
        from core.models import TaskFlag
        if self.__task_flags is None and not force_query:
            self.load_task_flags()  # only when the query is not forced do we attempt to initialize

        if force_query:
            flag_obj = TaskFlag.get(
                content_type_id=self.get_content_type().id, record_id=self.id, flag=flag) if self.id else None
            self.__change_cached_flag(flag, flag_obj)
        else:
            flag_obj = self.__task_flag_objs.get(flag)
        return flag_obj

    def get_flag_value(self, flag: str, force_query=False, default=None) -> Optional[str]:
        """
        Return the flag value for this record

        :param: flag: is a flag name - essentially the key for the flag
        :param: force_query: True/False to perform a query ignoring the cached values
        :return: TaskFlag object instance
        """
        flag_obj = self.get_flag(flag, force_query)
        return flag_obj.value if flag_obj else default

    @classmethod
    def get_flags(cls, flag: str) -> QuerySet:
        """
        Get all flag records for this model with this flag name
        """
        from core.models import TaskFlag
        return TaskFlag.filter(content_type_id=cls.get_content_type().id, flag=flag)

    @classmethod
    def get_global_flags(cls) -> QuerySet:
        """
        Get all global flag records for this model with this flag name
        """
        from core.models import TaskFlag
        return TaskFlag.filter(content_type_id=cls.get_content_type().id, record_id=0)

    @classmethod
    def get_global_flag(cls, flag: str):
        """
        Get global flag record for this model with this flag name
        """
        from core.models import TaskFlag
        return TaskFlag.get(content_type_id=cls.get_content_type().id, flag=flag, record_id=0)

    @classmethod
    def get_global_flag_value(cls, flag: str, default=None) -> Optional[str]:
        """
        Return the global flag value for this model

        :param: flag: is a flag name - essentially the key for the flag
        :return: TaskFlag object instance
        """
        flag_obj = cls.get_global_flag(flag)
        return flag_obj.value if flag_obj else default

    @classmethod
    def _model_name(cls):
        return cls._meta.model.__name__

    @classmethod
    def set_global_flag(cls, flag: str, value: str = ''):
        """
        Set the flag for this record
        """
        from core.models import TaskFlag
        flag_obj = TaskFlag.set_global(cls, flag, value)
        if flag_obj:
            if flag_obj == flag:
                print(f'"{flag}" Global {cls._model_name()} Flag set.', True)
            else:
                print(f'"{flag}" Global {cls._model_name()} Flag created.', True)
        else:
            print(f'"{flag}" Global {cls._model_name()} Flag already set.', True)

    def set_flag(self, flag: str, value: str = ''):
        """
        Set the flag for this record
        """
        from core.models import TaskFlag
        flag_obj = TaskFlag.set(self, flag, value)
        self.__change_cached_flag(flag, flag_obj)
        if flag_obj:
            if flag_obj == flag:
                print(f'"{flag}" {self._model_name()}[{self.id}] Flag set.', True)
            else:
                print(f'"{flag}" {self._model_name()}[{self.id}] Flag created.', True)
        else:
            print(f'"{flag}" {self._model_name()}[{self.id}] Flag already set.', True)

    def unset_flag(self, flag: str):
        """
        Remove flag for this record
        """
        flag_obj = self.get_flag(flag)
        self.__change_cached_flag(flag, None)
        if flag_obj:
            flag_obj.delete()
            print(f'"{flag}" {self._model_name()}[{self.id}] Flag removed.', True)
        else:
            print(f'"{flag}" {self._model_name()}[{self.id}] Flag does not exist.', True)

    @classmethod
    def unset_global_flag(cls, flag: str):
        """
        Remove global flag for this model
        """
        flag_obj = cls.get_global_flag(flag)
        if flag_obj:
            flag_obj.delete()
            print(f'"{flag}" Global {cls._model_name()} Flag removed.', True)
        else:
            print(f'"{flag}" Global {cls._model_name()} Flag does not exist.', True)

    class Meta:
        abstract = True


class AutoDateMixin(BaseModel):
    """ Adds created and updated fields to Model (auto_now) """
    created = models.DateTimeField("Created Date")
    updated = models.DateTimeField("Date Updated")

    @property
    def get_last_update(self):
        import core.views.helpers as vh
        return vh.get_change_history(type(self), 1, None, self.pk)

    get_last_update.fget.short_description = 'Returns the last change history record.'
    get_last_update.fget.help_text = ''

    @property
    def last_updated(self):
        text = 'Never'
        obj = self.get_last_update
        if obj:
            text = '{1} ({0})'.format(obj[0].user.username, obj[0].created.strftime('%Y-%m-%d %I:%M %p'))
        return text

    last_updated.fget.short_description = 'Returns the last change history record as a formatted string value.'

    @staticmethod
    def update_kwargs(kwargs: Optional[dict], field_list):
        if type(kwargs) is dict:
            if 'update_fields' in kwargs and type(kwargs['update_fields']) is list:
                if type(field_list) is str:
                    field_list = field_list.split(',')
                kwargs['update_fields'].extend(field_list)
                return True  # updated
            return False  # unexpected format
        return None  # nothing to do

    def update_changed_field_kwargs(self, kwargs, kv: dict):
        field_list = []
        for k, v in kv.items():
            if not getattr(self, k) == v:
                setattr(self, k, v)
                field_list.append(k)
        if self.update_kwargs(kwargs, field_list) is False:
            kwargs.update(kv)

    @staticmethod
    def get_pop_dict(dict_obj, key, default=None):
        if dict_obj and type(dict_obj) is dict and key in dict_obj:
            value = dict_obj[key]
            del dict_obj[key]
            return value
        return default

    def save(self, *args, **kwargs):
        """
        Update the created and updated fields even if they were not specified while saving
        :param args: the args
        :param kwargs: the kwargs
        :return: Nothing
        """
        exclude_auto_user = False
        if 'exclude_auto_user' in kwargs:
            exclude_auto_user = True if kwargs['exclude_auto_user'] else False
            kwargs.pop('exclude_auto_user')

        if 'update_fields' in kwargs:
            if kwargs['update_fields']:
                kwargs['update_fields'].extend(['updated', 'created'])
                if not exclude_auto_user and hasattr(self, 'last_user') and 'last_user' not in kwargs['update_fields']:
                    # only do this if we don't exempt ourselves from it
                    from django_currentuser.middleware import get_current_user
                    current_user = get_current_user()
                    if current_user:
                        self.last_user = current_user
                        kwargs['update_fields'].append('last_user')

        if self.created is None:  # moved before updated
            self.created = tz.localtime()

        if not kwargs.get('skip_updated_dt'):
            self.updated = tz.localtime()
        else:
            kwargs.pop('skip_updated_dt')

        super_model = super(AutoDateMixin, self)

        super_model.save(*args, **kwargs)

    class Meta:
        abstract = True


class SourceModelMixin(BaseModel):
    """ Adds record_source field to Model (reference to RecordSource Model) """
    record_source = models.CharField('Source Signature', null=True, default=None, max_length=256)

    def save(self, *args, **kwargs):
        from core.models import RecordSource
        if self.record_source is None:
            self.record_source = RecordSource.objects.get(value='ag')
            if 'update_fields' in kwargs:
                kwargs['update_fields'] = list(kwargs.get('update_fields')).append('record_source')

        super(SourceModelMixin, self).save(*args, **kwargs)

    class Meta:
        abstract = True


class AttributePropertyMixin(BaseModel):
    """
    Adds attribute and value fields to the model. Use the val property as the getter and setter.
    """
    parent_field = None
    model_attributes = None
    hidden_model_attributes = None
    attribute_sequence_name = 'Default'

    attribute = models.ForeignKey('core.CustomAttribute',
                                  related_name="%(app_label)s_%(class)s_atx",
                                  on_delete=models.CASCADE)
    value = models.TextField(default=None, null=True)

    def __str__(self):
        return f"{self.parent_field}.{self.attribute.uuid} = {self.value}"

    def __repr__(self):
        return f"{self.parent_field}.{self.attribute.uuid} = {self.value}"

    @property
    def name(self):
        return self.attribute.name

    @property
    def val(self):
        this_val = self.value
        if self.attribute.type in ['datetime', 'date'] and this_val is not None:
            return tz.loads(this_val) if self.attribute.type == 'datetime' else tz.loads(this_val, tz.DT24_FMT_3_D)
        elif self.attribute.type in ['float'] and this_val is not None:
            return float(this_val)
        else:
            try:
                return json.loads(this_val) if this_val is not None else None
            except:
                return this_val

    @val.setter
    def val(self, value):
        if self.attribute.type in ['datetime', 'date'] and value is not None:
            self.value = tz.dumps(value) if self.attribute.type == 'datetime' else tz.dumps(value, tz.DT24_FMT_3_D)
        else:
            self.value = json.dumps(value) if value is not None else None

    @classmethod
    def validate_model_attributes(cls, org_id, save_on_existing=True):
        from magic.conf import cached_var, NO_CACHE, set_var
        from core.models import CustomAttribute
        parent = cls.get_parent()
        ct = parent.related_model.get_content_type()
        key_name = f"{ct.app_label}_{ct.model}_validated_attributes_{org_id}".lower()

        return_value = cached_var(key_name, 60)
        if return_value == NO_CACHE or return_value is False:
            for ma in cls.model_attributes:
                CustomAttribute.setup_attribute(ma, parent, org_id, True,
                                                cls.attribute_sequence_name, save_on_existing)
            for ma in cls.hidden_model_attributes:
                CustomAttribute.setup_attribute(ma, parent, org_id, False,
                                                cls.attribute_sequence_name, save_on_existing)
            set_var(key_name, True, 60)

    @classmethod
    def get_prop(cls, parent_obj, attr):
        attr_field = cls.get_attr_field(attr)
        find_obj = cls.get_finder_obj(parent_obj, attr, attr_field)
        if hasattr(parent_obj, 'properties'):  # attempt to get properties from the parent object (might be prefetched)
            prop = parent_obj.properties.filter(**{attr_field: attr})
            if prop:
                return prop.first()
        else:  # otherwise, the properties are not directly searchable from the object
            return cls.get(**find_obj)
        return None

    @classmethod
    def get_attr_field(cls, attr):
        attr_field = 'attribute'
        if type(attr) is int:
            attr_field = 'attribute_id'
        return attr_field

    @classmethod
    def get_finder_obj(cls, parent_obj, attr, attr_field=None):
        if attr_field is None:
            attr_field = cls.get_attr_field(attr)
        return {cls.parent_field: parent_obj, attr_field: attr}

    @classmethod
    def set_prop(cls, parent_obj, attr, value):
        """
        A way to set properties by object
        :param parent_obj: an object whose model inherits AttributePropertyMixin
        :param attr: a core.CustomAttribute object, or it's id
        :param value: a JSON serializable object (attribute type determines how it will be serialized)
        """
        find_obj = cls.get_finder_obj(parent_obj, attr)
        new_obj = find_obj.copy()
        new_obj['value'] = value
        new_obj['wsrep_autolog'] = False  # disable wsrep logging

        update = False

        prop = cls.get_prop(parent_obj, attr)

        if not prop:  # we didn't find the property...
            try:
                prop = cls.create_model(**new_obj)  # try to create
            except django.db.IntegrityError:  # detected that the record exists...
                # attempting to re-associate orphaned properties...
                if hasattr(parent_obj, 'properties'):
                    prop = cls.get(**find_obj)
                    if prop:
                        update = True
                        parent_obj.properties.add(prop)
        else:
            update = True

        if update and prop:  # we only update if there was already an existing property
            pre = prop.val
            prop.val = value
            if pre != prop.val:
                prop.save(update_fields=['value'])
        elif prop and hasattr(parent_obj, 'properties'):
            parent_obj.properties.add(prop)  # this will likely never happen, but this is here just-in-case

        return prop

    @classmethod
    def get_parent(cls):
        if not cls.parent_field:
            raise Exception("Model config is missing parent_field property!")
        parent = getattr(cls, cls.parent_field)
        if parent and hasattr(parent, 'field'):
            parent = parent.field
        if type(parent) is not models.ForeignKey:
            raise Exception("Model config is invalid. The parent_field property must be a ForeignKey field name!")
        return parent

    @classmethod
    def available_attributes(cls, org_id: int, show_all: bool = True):
        from core.models import CustomAttribute
        parent = cls.get_parent()
        return CustomAttribute.available_attributes(org_id, parent.related_model, show_all)

    class Meta:
        abstract = True


class AutoDateAndSourceMixin(SourceModelMixin, AutoDateMixin):
    class Meta:
        abstract = True


class GenericListMixin(models.Model):  # reused fields for lists

    def add_to_list(self, list_field: str, single_field: str, obj, set_main=False):
        ol = list(getattr(self, list_field).all())
        if obj not in ol:
            getattr(self, list_field).add(obj)
            if set_main and single_field and hasattr(self, single_field):
                setattr(self, single_field, obj)
                self.save(update_fields=[single_field])
            return True
        return False

    def remove_from_list(self, list_field: str, single_field: str, obj, allow_empty=False, set_main=False):
        ol = list(getattr(self, list_field).all())
        if (len(ol) > 1 or allow_empty) and obj in ol:
            getattr(self, list_field).remove(obj)
            if set_main and single_field and hasattr(self, single_field):
                if obj == getattr(self, single_field):
                    if allow_empty:
                        setattr(self, single_field, None)
                    else:
                        for o in ol:
                            if not ol == obj:
                                setattr(self, single_field, o)
                                return o  # if set main is specified and the value is changed, return the value
                    self.save(update_fields=[single_field])
            return True
        return False

    def get_list(self, list_field: str, single_field: str):
        """ self:arg
            This is used to combine the single (primary) field object with the list data
        """
        ol = []
        original_list = getattr(self, list_field).all()

        # this was modified to always add the single value to the list first
        if single_field and hasattr(self, single_field):
            # when changing over to the new field, we must be aware of the previous data
            old = getattr(self, single_field)
            if old:
                ol.append(old)
                if old not in original_list:
                    getattr(self, list_field).add(old)

        for record in original_list:
            if record not in ol:
                ol.append(record)

        return ol

    class Meta:
        abstract = True


class ParentChildMixin(BaseModel):
    parent = models.ForeignKey('self', on_delete=models.CASCADE, related_name='%(app_label)s_%(class)s_parent',
                               null=True, default=None, verbose_name="Parent")

    @classmethod
    def get_children_from_parent(cls, parent_id: Union[int, Type[int]], max_levels: int = 5) -> QuerySet:
        """
        Get the queryset containing all of the children for a specified parent

        :param parent_id: the parent id we are wanting data for
        :param max_levels: maximum number of child objects to return, default=5
        :return: QuerySet object containing all of the children of the given parent
        """
        max_levels -= 1
        ps = "parent"
        filters = Q()
        filters.connector = Q.OR
        filters.add(Q((f'{ps}_id', parent_id)), Q.OR)
        while max_levels > 0:
            ps += "__parent"
            filters.add(Q((f'{ps}_id', parent_id)), Q.OR)
            max_levels -= 1  # decrement

        return cls.objects.filter(filters)

    def get_children_option(self, max_levels: int = 5) -> QuerySet:
        """
        Get the queryset containing all children for the current object

        :param max_levels: maximum number of child objects to get, default=5
        :return: QuerySet object containing all of the children of the current object
        """
        return self.get_children_from_parent(self.id, max_levels=max_levels)

    @classmethod
    @unnamed_cache(5)
    def get_child_ids(cls, parent_id: Union[int, Type[int]], max_levels: int = 5) -> List:
        child_list = []
        children = cls.get_children_from_parent(parent_id, max_levels)
        if children:
            for child in children:
                if child.id not in child_list:
                    child_list.append(child.id)
        return child_list

    @classmethod
    def get_traversable_parent(cls, parent_id: Union[int, Type[int]], max_levels: int = 5) -> Optional['BaseModel']:
        """
        Return single instance of this model that matches the parent_id,
        but also pre-select parent fields up to 5 levels deep

        :param parent_id: the parent id we are wanting
        :param max_levels: maximum number of parent objects to prefetch, default=5
        :return: model object where id=parent_id for the current model class
        """
        max_levels -= 1
        related_list = ['parent']
        while max_levels > 0:
            related_list += [str(related_list[len(related_list) - 1]) + '__parent']
            max_levels -= 1  # decrement

        return cls.get(id=parent_id, select_related=related_list)

    @classmethod
    def get_parent_ids_by_id(cls, obj_id, max_levels: int = 5) -> List:
        """
        Return cached list of IDs which are the parents for the current model record

        :param obj_id: the model object record id
        :param max_levels: maximum number of parent objects to prefetch, default=5
        :return: List object containing 0 or more parent ids
        """
        this_obj = cls.by_id(obj_id)
        return this_obj.get_ordered_parent_ids(max_levels)

    @classmethod
    def get_parent_ids(cls, obj_or_id, max_levels: int = 5):
        """
        Return cached list of IDs which are the parents for the current model record

        :param obj_or_id: an id or an object that is based on the ParentChildMixin
        :param max_levels: maximum number of parent objects to prefetch, default=5
        :return: List object containing 0 or more parent ids
        """
        if obj_or_id and str(obj_or_id).isnumeric():
            return cls.get_parent_ids_by_id(obj_or_id, max_levels)
        elif obj_or_id and hasattr(obj_or_id, 'get_ordered_parent_ids'):
            return obj_or_id.get_ordered_parent_ids(max_levels)
        return []

    def get_ordered_parent_ids(self, max_levels: int = 5) -> List:
        """
        Get an ordered list of ids for all parents of the current record

        :param max_levels: maximum number of parent objects to prefetch, default=5
        :return: List object containing 0 or more parent ids
        """
        current_parent = self.get_traversable_parent(self.parent_id, int(max_levels)) if self.parent_id else None
        parent_ids = [self.parent_id] if self.parent_id else []

        max_levels -= 1
        while current_parent and max_levels > 0:  # loop through all parents of the current record, add id to the list
            if current_parent.parent_id not in parent_ids:
                parent_ids += [current_parent.parent_id] if current_parent.parent_id else []
            current_parent = current_parent.parent if current_parent.parent_id else None
            max_levels -= 1  # decrement current level

        return parent_ids

    def get_parents(self) -> QuerySet:
        """
        Get all parent objects for the current model

        :return: QuerySet containing parents of the current model (unordered)
        """
        parent_ids = self.get_ordered_parent_ids()
        return self.__class__.filter(id__in=parent_ids) if parent_ids else QuerySet(self.__class__.all())

    @unnamed_cache(5)
    def get_ordered_parents(self) -> List:
        """
        Get all parent objects for the current model - Avoids unnecessary queries

        :return: List containing parents of the current model (in order)
        """
        parent_ids = self.get_ordered_parent_ids()
        if parent_ids:
            qs = self.__class__.filter(id__in=parent_ids)
            if qs:
                parent_objects = dict([(obj.id, obj) for obj in qs])
                return [parent_objects[obj_id] for obj_id in parent_ids]
        return []

    class Meta:
        abstract = True


class OrganizationMixin(models.Model):
    org_optional = False
    organization = models.ForeignKey('core.Organization',
                                     related_name="%(app_label)s_%(class)s_org",
                                     on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        if hasattr(self, 'organization') and not self.organization_id:
            self.organization_id = dj_cfg.DEFAULT_ORG_ID
        super(OrganizationMixin, self).save(*args, **kwargs)

    class Meta:
        abstract = True


class OptionalOrganizationMixin(models.Model):
    org_optional = True  # can be turned off for abstract classes
    force_org_null = False
    organization = models.ForeignKey('core.Organization',
                                     null=True, default=None,
                                     related_name="%(app_label)s_%(class)s_org",
                                     on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        if not self.org_optional and hasattr(self, 'organization') and not self.organization_id:
            self.organization_id = dj_cfg.DEFAULT_ORG_ID
        elif self.org_optional and self.force_org_null:
            self.organization_id = None
        super(OptionalOrganizationMixin, self).save(*args, **kwargs)

    class Meta:
        abstract = True


class OrganizationListMixin(BaseModel, GenericListMixin):
    organization_list = models.ManyToManyField('core.Organization',
                                               # how to generate a good related name
                                               related_name="%(app_label)s_%(class)s_org_list")
    organization_list_id_cache = models.CharField(max_length=512, default='', null=True)
    last_org_cache = models.DateTimeField(default=None, null=True)

    def add_organization(self, organization, set_main=False):
        result = self.add_to_list('organization_list', 'organization', organization, set_main)
        self.last_org_cache = None
        ol = self.organizations
        return result

    def remove_organization(self, organization, allow_empty=False, set_main=False):
        self.remove_from_list('organization_list', 'organization', organization, allow_empty, set_main)
        self.last_org_cache = None
        ol = self.organizations

    def clear_organization_list(self):
        self.organization_list.clear()
        # self.save(update_fields=['organization_list'])

    @classmethod
    def build_all_org_cache(cls):
        from core.models import Log
        for obj in cls.get_models():
            obj.build_org_cache()
        Log.info('Done!')

    def build_org_cache(self):
        from core.models import Log
        try:
            Log.info('Caching: {0}'.format(str(self)))
            self.last_org_cache = None
            ol = self.organizations
        except Exception as ex:
            Log.error("Failed!", ex=ex)

    @property
    def organizations(self):
        curr_time = tz.localtime()

        org_list = self.get_list('organization_list', 'organization')

        if not self.last_org_cache or (self.last_org_cache + tz.timedelta(hours=1)) <= curr_time:
            id_list = "|"
            for org in org_list:
                id_list += str(org.id) + "|"

            if not id_list == self.organization_list_id_cache:
                self.organization_list_id_cache = id_list
                self.last_org_cache = curr_time
                self.save(update_fields=['organization_list_id_cache', 'last_org_cache'])
            else:
                self.last_org_cache = curr_time
                self.save(update_fields=['last_org_cache'])
        return org_list

    def organization_ids(self):
        org_list = []
        for org in self.organization_list.all():
            if org.id not in org_list:
                org_list.append(org.id)
        return org_list

    def organization_name_list(self):
        return [org.name for org in self.organizations]

    def organization_name_list_string(self):
        names = ""
        for name in self.organization_name_list():
            names += name if names == "" else ", " + name
        return names if names else None

    class Meta:
        abstract = True


class MultiOrgMixin(OrganizationMixin, OrganizationListMixin):
    """
    For models that need the organization and organization_list fields
    """
    class Meta:
        abstract = True


class AccountListMixin(BaseModel, GenericListMixin):
    account_list = models.ManyToManyField('core.Account',
                                          # how to generate a good related name
                                          related_name="%(app_label)s_%(class)s_acct_list")

    def add_account(self, account, set_main=False):
        return self.add_to_list('account_list', 'account', account, set_main)

    def remove_account(self, account, allow_empty=False, set_main=False):
        self.remove_from_list('account_list', 'account', account, allow_empty, set_main)

    @property
    def accounts(self):
        return self.get_list('account_list', 'account')

    class Meta:
        abstract = True


class ServiceAreaListMixin(BaseModel, GenericListMixin):
    area_list = models.ManyToManyField('dispatch.ServiceArea',
                                       # how to generate a good related name
                                       related_name="%(app_label)s_%(class)s_area_list")

    def add_area(self, area, set_main=False):
        return self.add_to_list('area_list', 'area', area, set_main)

    def remove_area(self, area, allow_empty=False, set_main=False):
        self.remove_from_list('area_list', 'area', area, allow_empty, set_main)

    @property
    def areas(self):
        return self.get_list('area_list', 'area')

    class Meta:
        abstract = True


class ProductLineListMixin(BaseModel, GenericListMixin):
    product_line_list = models.ManyToManyField('dispatch.ProductLineType',
                                               # how to generate a good related name
                                               related_name="%(app_label)s_%(class)s_prodline_list")

    def add_product_line(self, product_line, set_main=False):
        return self.add_to_list('product_line_list', 'product_line', product_line, set_main)

    def remove_product_line(self, product_line, allow_empty=False, set_main=False):
        if self.product_line_id == product_line.id:
            self.remove_from_list('product_line_list', 'product_line', product_line, allow_empty, True)
        else:
            self.remove_from_list('product_line_list', 'product_line', product_line, allow_empty, set_main)

    @property
    def product_lines(self):
        return self.get_list('product_line_list', 'product_line')

    @property
    def product_line_id_list(self):
        return [plt.id for plt in self.product_lines]

    class Meta:
        abstract = True


class ProductListMixin(BaseModel, GenericListMixin):
    product_list = models.ManyToManyField('core.Product',
                                          # how to generate a good related name
                                          related_name="%(app_label)s_%(class)s_product_list")

    def add_product(self, product, set_main=False):
        return self.add_to_list('product_list', 'product', product, set_main)

    def remove_product(self, product, allow_empty=False, set_main=False):
        self.remove_from_list('product_list', 'product', product, allow_empty, set_main)

    @property
    def products(self):
        return self.get_list('product_list', 'product')

    class Meta:
        abstract = True


class ContactListMixin(BaseModel, GenericListMixin):
    contact_list = models.ManyToManyField('core.Contact',
                                          # how to generate a good related name
                                          related_name="%(app_label)s_%(class)s_cont_list")

    def add_contact(self, contact, set_main=False):
        return self.add_to_list('contact_list', 'contact', contact, set_main)

    def remove_contact(self, contact, allow_empty=False, set_main=False):
        self.remove_from_list('contact_list', 'contact', contact, allow_empty, set_main)

    @property
    def contacts(self):
        return self.get_list('contact_list', 'contact')

    @classmethod
    def find_by_contact(cls, contact, organization=None):
        qs = cls.org_qs(organization)
        c_filter = {}
        if hasattr(cls, 'contact'):
            c_filter['contact'] = contact
        if hasattr(cls, 'contact_list'):
            c_filter['contact_list__in'] = [contact]
        return qs.filter(**c_filter)

    class Meta:
        abstract = True


# class DivisionListMixin(BaseModel, GenericListMixin):  # for divisions
#     division_list = models.ManyToManyField('core.Division',
#                                            # how to generate a good related name
#                                            related_name="%(app_label)s_%(class)s_div_list")
#
#     def add_division(self, division, set_main=False):
#         return self.add_to_list('division_list', 'division', division, set_main)
#
#     def remove_division(self, division, allow_empty=False, set_main=False):
#         self.remove_from_list('division_list', 'division', division, allow_empty, set_main)
#
#     @property
#     def divisions(self):
#         return self.get_list('division_list', 'division')
#
#     class Meta:
#         abstract = True


class TowerListMixin(BaseModel, GenericListMixin):  # for divisions
    tower_list = models.ManyToManyField('inven.TowerDetail',
                                        # how to generate a good related name
                                        related_name="%(app_label)s_%(class)s_tower_list")

    def add_tower(self, tower, set_main=False):
        return self.add_to_list('tower_list', 'tower', tower, set_main)

    def remove_tower(self, tower, allow_empty=False, set_main=False):
        self.remove_from_list('tower_list', 'tower', tower, allow_empty, set_main)

    @property
    def towers(self):
        return self.get_list('tower_list', 'tower')

    class Meta:
        abstract = True


# class AddressMixin(BaseModel):
#     service_address = models.ForeignKey('core.Address', models.SET_NULL,
#                                         '%(app_label)s_%(class)s_serviceaddr', null=True, default=None)
#     billing_address = models.ForeignKey('core.Address', models.SET_NULL,
#                                         '%(app_label)s_%(class)s_billingaddr', null=True, default=None)
#     alt_address = models.ForeignKey('core.Address', models.SET_NULL,
#                                     '%(app_label)s_%(class)s_altaddr', null=True, default=None)
#
#     @property
#     def addresses(self):
#         address = []
#         if self.service_address:
#             address.append({'field': 'service_address',
#                             'object': self.service_address})
#         if self.billing_address:
#             address.append({'field': 'billing_address',
#                             'object': self.billing_address})
#         if self.alt_address:
#             address.append({'field': 'alt_address',
#                             'object': self.alt_address})
#         return address if address else None
#
#     class Meta:
#         abstract = True


class UniqueAddressMixin(BaseModel):
    service_addr = models.ForeignKey('core.AddressUnique', models.SET_NULL,
                                     '%(app_label)s_%(class)s_userviceaddr', null=True, default=None)
    billing_addr = models.ForeignKey('core.AddressUnique', models.SET_NULL,
                                     '%(app_label)s_%(class)s_ubillingaddr', null=True, default=None)
    alt_addr = models.ForeignKey('core.AddressUnique', models.SET_NULL,
                                 '%(app_label)s_%(class)s_ualtaddr', null=True, default=None)

    def clear_all_addresses(self, save=True, only_invalid=False):
        fields = []
        # validate the existing data -- remove it if there's a problem or if we want to clear all
        if self.validate_field('service_addr') is None or only_invalid is False:
            self.service_addr = None
            fields.append("service_addr")
        if self.validate_field('billing_addr') is None or only_invalid is False:
            self.billing_addr = None
            fields.append("billing_addr")
        if self.validate_field('alt_addr') is None or only_invalid is False:
            self.alt_addr = None
            fields.append("alt_addr")
        if fields and save:
            self.save(update_fields=fields)
        return fields

    @classmethod
    def find_objects_with_address(cls, address) -> models.query.QuerySet:
        return cls.filter(Q(service_addr_id=address.id) | Q(billing_addr_id=address.id) | Q(alt_addr_id=address.id))

    @property
    def addrs(self):
        address = []
        if self.service_addr:
            address.append({'field': 'service_addr',
                            'object': self.service_addr})
        if self.billing_addr:
            address.append({'field': 'billing_addr',
                            'object': self.billing_addr})
        if self.alt_addr:
            address.append({'field': 'alt_addr',
                            'object': self.alt_addr})
        return address if address else None

    def serialize_address(self, field_name):
        addr = None
        if hasattr(self, field_name) and getattr(self, field_name):
            val = getattr(self, field_name)
            addr = val.serialize_me()
            addr['field'] = field_name
        return addr

    @property
    def addrs_ser(self):
        address = []
        if self.service_addr:
            address.append(self.serialize_address('service_addr'))
        if self.billing_addr:
            address.append(self.serialize_address('billing_addr'))
        if self.alt_addr:
            address.append(self.serialize_address('alt_addr'))
        return address if address else None

    @property
    def get_address_list(self):
        address = []
        if self.service_addr:
            address.append(self.service_addr)
        if self.billing_addr:
            address.append(self.billing_addr)
        if self.alt_addr:
            address.append(self.alt_addr)
        return address if address else None

    class Meta:
        abstract = True


class PhoneMixin(BaseModel):
    home_phone = models.ForeignKey('core.PhoneContact', models.SET_NULL,
                                   "%(app_label)s_%(class)s_home_phone", null=True, default=None)
    mobile_phone = models.ForeignKey('core.PhoneContact', models.SET_NULL,
                                     "%(app_label)s_%(class)s_mobile_phone", null=True, default=None)
    work_phone = models.ForeignKey('core.PhoneContact', models.SET_NULL,
                                   "%(app_label)s_%(class)s_work_phone", null=True, default=None)
    phone_list = models.ManyToManyField('core.PhoneContact', "%(app_label)s_%(class)s_alt_phone")

    @classmethod
    def find_by_partial_phone(cls, phone, region='US', org=None):
        from core.models import PhoneContact
        formatted_obj = PhoneContact.get_formatted(phone, region, False)
        search = None
        if formatted_obj:
            search = "{0}x{1}".format(formatted_obj['number'], formatted_obj['extension']) \
                if formatted_obj['extension'] else formatted_obj['number'] if 'number' in formatted_obj else None
        if search:
            qs = cls.org_qs(org)
            return qs.filter(
                Q(home_phone__number__endswith=search) |
                Q(mobile_phone__number__endswith=search) |
                Q(work_phone__number__endswith=search)
            )
        return None

    @classmethod
    def find_by_phone(cls, phone, region='US'):
        from core.models import PhoneContact
        obj = PhoneContact.check_existing(phone, region)
        if obj:
            return cls.get_models(
                Q(home_phone=obj) |
                Q(mobile_phone=obj) |
                Q(work_phone=obj) |
                Q(phone_list__in=[obj])
            )
        return None

    @classmethod
    def find_by_phone_obj_list(cls, phone_obj_list):
        if phone_obj_list and type(phone_obj_list) is list:
            return cls.get_models(
                Q(home_phone__in=phone_obj_list) |
                Q(mobile_phone__in=phone_obj_list) |
                Q(work_phone__in=phone_obj_list) |
                Q(phone_list__in=phone_obj_list)
            )
        return None

    def clear_all_phone_numbers(self, save=True):
        fields = ['home_phone', 'mobile_phone', 'work_phone']
        self.home_phone = None
        self.mobile_phone = None
        self.work_phone = None
        self.phone_list.clear()
        if save:
            self.save(update_fields=fields)
        return fields

    def remove_phone_contacts(self, pc_id_list):
        fields = []
        this_list = [pc.id for pc in self.phone_list.all()]
        for pc in pc_id_list:
            if self.home_phone and self.home_phone_id == pc:
                self.home_phone = None
                fields.append('home_phone')
            if self.mobile_phone and self.mobile_phone_id == pc:
                self.mobile_phone = None
                fields.append('mobile_phone')
            if self.work_phone and self.work_phone_id == pc:
                self.work_phone = None
                fields.append('work_phone')
            if pc in this_list:
                self.phone_list.remove(pc)

        if fields:
            self.save(update_fields=fields)
        return fields

    def merge_phone_contacts(self, pc_id_list):
        fields = []
        this_list = [pc.id for pc in self.phone_list.all()]
        for pc in pc_id_list:
            if not self.home_phone:
                self.home_phone_id = pc
                fields.append('home_phone')
            elif not self.mobile_phone:
                self.mobile_phone_id = pc
                fields.append('mobile_phone')
            elif not self.work_phone:
                self.work_phone_id = pc
                fields.append('work_phone')
            if pc not in this_list:
                self.phone_list.add(pc)
        if fields:
            self.save(update_fields=fields)
        return fields

    def has_phone_number(self, phone_obj=None, phone=None, region='US'):
        from core.models import PhoneContact
        if not phone_obj and phone:
            phone_obj = PhoneContact.get_number_object(phone, region)
        found = False
        used_fields = []
        found_fields = []
        if phone_obj and self.phone_numbers:
            for number in self.phone_numbers:
                if not number['field'] == 'alt_phone':
                    used_fields.append(number['field'])
                if number['object'] == phone_obj:
                    found = True
                    if not number['field'] == 'alt_phone':
                        found_fields.append(number['field'])

        return found, used_fields, found_fields

    def get_phone_number_result(self, phone_obj=None, phone=None, region='US'):
        from core.models import PhoneContact
        if not phone_obj and phone:
            phone_obj = PhoneContact.get_number_object(phone, region)
        if phone_obj and self.phone_numbers:
            for number in self.phone_numbers:
                if number['object'] == phone_obj:
                    return number  # only the match is returned
        return None

    def make_and_add_phone(self, number, region='US', user=None, org=None):
        obj = self.get_or_make_phone_contact_object(user, number, region, org)
        result = {
            'assigned': False, 'found': False, 'fields': [],
            'updated_alt': False, 'found_fields': [], 'object': None}
        if obj:
            result = self.add_phone_number(obj, False)
            result['object'] = obj
        return result

    @classmethod
    def get_or_make_phone_contact_object(cls, user, number, region='US', org=None):
        from core.models import PhoneContact
        res = PhoneContact.create_number(user, number, region, org)
        return res['object'] if not res['result'] == 'failure' else None

    def add_phone_number(self, pc_obj, save=True, alt_only=False):
        assigned = False
        field_order = ['home_phone', 'mobile_phone', 'alt_phone']
        found, used_fields, found_fields = self.has_phone_number(pc_obj)
        alt_update = False
        updated_fields = []

        if not found:
            for field in field_order:
                if field not in used_fields:
                    if field == 'alt_phone' or alt_only:
                        self.phone_list.add(pc_obj)
                        alt_update = True
                    else:
                        setattr(self, field, pc_obj)
                        used_fields.append(field)
                        updated_fields.append(field)
                    assigned = True
                    break
            if save and updated_fields:
                self.save(update_fields=updated_fields)
        return {'assigned': assigned, 'found': found, 'fields': updated_fields,
                'updated_alt': alt_update, 'found_fields': found_fields}

    @property
    def phone_1(self):
        pn = self.phone_numbers
        return pn[0]['number'] if pn and len(pn) > 0 else ''

    @property
    def phone_2(self):
        pn = self.phone_numbers
        return pn[1]['number'] if pn and len(pn) > 1 else ''

    @property
    def phone_3(self):
        pn = self.phone_numbers
        return pn[2]['number'] if pn and len(pn) > 2 else ''

    @property
    def phone_1_id(self):
        pn = self.phone_numbers
        return pn[0]['object'].id if pn and len(pn) > 0 else ''

    @property
    def phone_2_id(self):
        pn = self.phone_numbers
        return pn[1]['object'].id if pn and len(pn) > 1 else ''

    @property
    def phone_3_id(self):
        pn = self.phone_numbers
        return pn[2]['object'].id if pn and len(pn) > 2 else ''

    @property
    def phone_number_list(self):
        pl = [self.phone_1, self.phone_2, self.phone_3]
        if pl[1] == pl[0]:
            pl[1] = ''
        if pl[2] == pl[1] or pl[2] == pl[0]:
            pl[2] = ''
        return pl

    @property
    def phone_numbers(self):
        numbers = []
        if self.home_phone:
            numbers.append({'field': 'home_phone',
                            'object': self.home_phone,
                            'number': self.home_phone.number,
                            'info': str(self.home_phone),
                            'extension': self.home_phone.extension})
        if self.mobile_phone:
            numbers.append({'field': 'mobile_phone',
                            'object': self.mobile_phone,
                            'number': self.mobile_phone.number,
                            'info': str(self.mobile_phone),
                            'extension': self.mobile_phone.extension})
        if self.work_phone:
            numbers.append({'field': 'work_phone',
                            'object': self.work_phone,
                            'number': self.work_phone.number,
                            'info': str(self.work_phone),
                            'extension': self.work_phone.extension})
        for alt_phone in self.phone_list.all():
            numbers.append({'field': 'alt_phone',
                            'object': alt_phone,
                            'number': alt_phone.number,
                            'info': str(alt_phone),
                            'extension': alt_phone.extension})
        return numbers if numbers else None

    @property
    def phone_numbers_ser(self):
        numbers = []
        if self.home_phone:
            numbers.append({'field': 'home_phone',
                            'id': self.home_phone.id,
                            'number': self.home_phone.number,
                            'info': str(self.home_phone),
                            'extension': self.home_phone.extension})
        if self.mobile_phone:
            numbers.append({'field': 'mobile_phone',
                            'id': self.mobile_phone.id,
                            'number': self.mobile_phone.number,
                            'info': str(self.mobile_phone),
                            'extension': self.mobile_phone.extension})
        if self.work_phone:
            numbers.append({'field': 'work_phone',
                            'id': self.work_phone.id,
                            'number': self.work_phone.number,
                            'info': str(self.work_phone),
                            'extension': self.work_phone.extension})
        for alt_phone in self.phone_list.all():
            numbers.append({'field': 'alt_phone',
                            'id': alt_phone.id,
                            'number': alt_phone.number,
                            'info': str(alt_phone),
                            'extension': alt_phone.extension})
        return numbers if numbers else None

    class Meta:
        abstract = True


class RecordStatusMixin(BaseModel):
    default_status = 'a'
    status = models.ForeignKey('core.StatusType', on_delete=models.DO_NOTHING,
                               related_name="%(app_label)s_%(class)s_status")

    def save(self, *args, **kwargs):
        if not self.status_id:
            from core.models import StatusType
            org_id = dj_cfg.DEFAULT_ORG_ID
            if hasattr(self, 'organization'):
                if getattr(self, 'organization_id'):
                    org_id = getattr(self, 'organization_id')
            s_obj = StatusType.by_val(self.default_status, org=org_id)
            if s_obj:
                self.status_id = s_obj.id
                if 'update_fields' in kwargs and kwargs['update_fields'] \
                        and 'status' not in kwargs['update_fields'] and 'status_id' not in kwargs['update_fields']:
                    kwargs['update_fields'] += ['status']
        super(RecordStatusMixin, self).save(*args, **kwargs)

    class Meta:
        abstract = True


class EmailListMixin(BaseModel):
    email_list = models.ManyToManyField('core.EmailContact', "%(app_label)s_%(class)s_alt_email")

    @classmethod
    def find_by_email(cls, email, org=None):
        from core.models import EmailContact, Organization
        email_obj = EmailContact.check_existing(email)
        if email_obj:
            qs = cls.org_qs(org)
            if hasattr(cls, 'primary_email'):
                return qs.filter(
                    Q(primary_email=email_obj) |
                    Q(email_list__in=[email_obj])
                )
            else:
                return qs.filter(Q(email_list__in=[email_obj]))
        return None

    @classmethod
    def find_by_email_obj_list(cls, email_obj_list, org=None):
        from core.models import Organization
        if email_obj_list and type(email_obj_list) is list:
            qs = cls.org_qs(org)
            if hasattr(cls, 'primary_email'):
                return qs.filter(
                    Q(primary_email__in=email_obj_list) |
                    Q(email_list__in=email_obj_list)
                )
            else:
                return qs.filter(Q(email_list__in=email_obj_list))
        return None

    def clear_all_email_addresses(self, save=True):
        fields = []
        self.email_list.clear()
        if hasattr(self, 'primary_email'):
            fields = ['primary_email']
            self.primary_email = None

            if save:
                self.save(update_fields=['primary_email'])
        return fields

    def remove_email_contacts(self, ec_id_list):
        fields = []
        this_list = [ec.id for ec in self.email_list.all()]
        for ec in ec_id_list:
            if hasattr(self, 'primary_email'):
                if self.primary_email and self.primary_email_id == ec:
                    self.primary_email = None
                    fields.append('primary_email')
            if ec in this_list:
                self.email_list.remove(ec)

        if fields:
            self.save(update_fields=['primary_email'])
        return fields

    def merge_email_contacts(self, ec_id_list):
        fields = []
        this_list = [ec.id for ec in self.email_list.all()]
        for ec in ec_id_list:
            if hasattr(self, 'primary_email'):
                if not self.primary_email:
                    self.primary_email_id = ec
                    fields.append('primary_email')
            if ec not in this_list:
                self.email_list.add(ec)
        if fields:
            self.save(update_fields=['primary_email'])
        return fields

    @classmethod
    def qs_without_email(cls):
        # find all model records that are lacking email references
        if hasattr(cls, 'primary_email'):
            return cls.get_models().annotate(
                email_num=Count('email_list')).filter(Q(primary_email__isnull=False) | Q(email_num__gt=0))
        else:
            return cls.get_models().annotate(
                email_num=Count('email_list')).filter(Q(email_num__gt=0))

    @classmethod
    def get_or_make_email_contact_object(cls, user, email: str):
        from core.models import EmailContact
        res = EmailContact.create_address(user, cls.make_printable(email))
        return res['object'] if not res['result'] == 'failure' else None

    def make_and_add_email(self, email_address: str, user=None, save=True):
        from core.models import EmailContact
        pc_res = EmailContact.create_address(user, self.make_printable(email_address))
        if not pc_res['result'] == 'failure':
            add_res = self.add_email_address(pc_res['object'], save)
            return add_res['fields']
        return None

    def add_email_address(self, ec_obj, save=True):
        found = False
        assigned = False
        alt_update = False
        used_fields = []
        updated_fields = []
        if hasattr(self, 'primary_email'):
            field_order = ['primary_email']
            if self.primary_email:
                for email in self.email_addresses:
                    if not email['field'] == 'alt_email':
                        used_fields.append(email['field'])
                    if email['object'] == ec_obj:
                        found = True
        else:
            field_order = ['alt_email']

        if not found:
            for field in field_order:
                if field not in used_fields:
                    if field == 'alt_email':
                        self.email_list.add(ec_obj)
                        alt_update = True
                    else:
                        setattr(self, field, ec_obj)
                        used_fields.append(field)
                        updated_fields.append(field)
                    assigned = True
                    break

            if save and updated_fields:
                self.save(update_fields=updated_fields)
        return {'assigned': assigned, 'found': found, 'fields': updated_fields, 'updated_alt': alt_update}

    @property
    def email_contact_addresses(self) -> list:
        emails = []
        if hasattr(self, 'primary_email') and self.primary_email_id:
            emails.append(self.make_printable(self.primary_email.address))
        for alt_email in self.email_list.all():
            if alt_email.address not in emails:
                emails.append(self.make_printable(alt_email.address))
        return emails

    @property
    def email_addresses(self):
        emails = []
        if hasattr(self, 'primary_email') and self.primary_email:
            emails.append({'field': 'primary_email',
                           'object': self.primary_email,
                           'email': self.make_printable(self.primary_email.address),
                           'info': self.make_printable(self.primary_email.address)})
        for alt_email in self.email_list.all():
            emails.append({'field': 'alt_email',
                           'object': alt_email,
                           'email': self.make_printable(alt_email.address),
                           'info': self.make_printable(alt_email.address)})
        return emails if emails else None

    @property
    def email_addresses_ser(self):
        emails = []
        if hasattr(self, 'primary_email') and self.primary_email:
            emails.append({'field': 'primary_email',
                           'id': self.primary_email.id,
                           'email': self.make_printable(self.primary_email.address),
                           'info': self.make_printable(self.primary_email.address)})
        for alt_email in self.email_list.all():
            emails.append({'field': 'alt_email',
                           'id': alt_email.id,
                           'email': self.make_printable(alt_email.address),
                           'info': self.make_printable(alt_email.address)})
        return emails if emails else None

    class Meta:
        abstract = True


class EmailMixin(EmailListMixin):
    primary_email = models.ForeignKey('core.EmailContact', models.SET_NULL,
                                      "%(app_label)s_%(class)s_primary_email", null=True, default=None)

    class Meta:
        abstract = True


class SortableMixin(AutoDateMixin):
    sort_ord = models.IntegerField(default=0)
    # group_field_name = None  # fallback value...
    group_attr_list = None  # provide a list of field names that can potentially be used to set the order

    @classmethod
    def get_group_name(cls):
        if not cls.group_attr_list:
            if hasattr(cls, 'group_field_name'):
                return str(cls.group_field_name)
            raise Exception("SortableMixin requires potential group field names of foreign key fields")

        validated_list = []
        if cls.group_attr_list and type(cls.group_attr_list) is list:
            for name in cls.group_attr_list:
                if getattr(cls, name, None):
                    validated_list.append(name)

            if validated_list:
                return validated_list
        raise Exception("SortableMixin group field list is invalid")

    def get_grouping_filter_dict(self):
        group_name = self.get_group_name()
        if type(group_name) is list:
            final_dict = {}
            for name in group_name:
                final_dict[name] = getattr(self, name, None)
            return final_dict
        else:
            return {group_name: getattr(self, group_name, None)}

    def init_ord(self, save=False, save_all=False):
        filter_dict = self.get_grouping_filter_dict()
        # get the highest (in number, lowest in order) conditional model instance
        order = self.__class__.get_models(**filter_dict).order_by('-sort_ord')

        if order.count() > 1:
            self.sort_ord = order.first().sort_ord + 1
        else:
            self.sort_ord = 0
        if save:
            self.save(update_fields=['sort_ord'])
        if save_all:
            self.save()

    def move_ord(self, up=True, save_all=False):  # up=True move up, up=False move down in order
        if up:
            if self.sort_ord > 0:
                my_ord = self.sort_ord - 1
            else:
                return
        else:
            my_ord = self.sort_ord + 1
        filter_dict = self.get_grouping_filter_dict()
        filter_dict['sort_ord'] = my_ord
        order = self.__class__.get_models(**filter_dict)
        if order:
            order = order.first()
            if up:
                order.sort_ord += 1
            else:
                order.sort_ord -= 1
            order.save(update_fields=['sort_ord'])
            self.sort_ord = my_ord
        else:
            return

        if save_all:
            self.save()
        else:
            self.save(update_fields=['sort_ord'])

    def set_ord(self, ord_val, save_all=False):
        filter_dict_base = self.get_grouping_filter_dict()

        if ord_val > self.sort_ord:
            prev_filter = filter_dict_base.copy()
            prev_filter['sort_ord__lte'] = ord_val
            prev_filter['id__ne'] = self.id

            prev_records = self.get_models(**prev_filter).order_by('sort_ord')
            ord_idx = 0
            for rec in prev_records:
                rec.sort_ord = ord_idx
                rec.save(update_fields=['sort_ord'])
                ord_idx += 1
                print(rec.sort_ord)
        else:
            next_filter = filter_dict_base.copy()
            next_filter['sort_ord__gte'] = ord_val
            next_filter['id__ne'] = self.id

            next_records = self.get_models(**next_filter).order_by('sort_ord')
            ord_idx = ord_val + 1
            for rec in next_records:
                rec.sort_ord = ord_idx
                rec.save(update_fields=['sort_ord'])
                ord_idx += 1
                print(rec.sort_ord)

        self.sort_ord = ord_val
        if save_all:
            self.save()
        else:
            self.save(update_fields=['sort_ord'])

    class Meta:
        abstract = True


class ConditionalMixin(SortableMixin):
    """ Inherits the AutoDateMixin class -- used to create various conditional models """
    group_field_name = None  # status, for example

    attr = models.CharField(max_length=64)  # field name
    condition = models.ForeignKey('core.ConditionalSymbols',
                                  on_delete=models.DO_NOTHING)
    value = models.TextField(null=True, default=None)  # store in json dictionary format
    # {"value": val, "type": 'str/int/model/enumtypemodel/float/bool/date/datetime'}
    negate = models.BooleanField(default=False)  # logical NOT (!, ~)
    logical_and = models.BooleanField(default=True)  # logical AND (&) with previous statement, otherwise OR (|)
    group_prev = models.BooleanField(default=False)  # group last set group and then logical and/or this

    @staticmethod
    def val_type(obj_val):
        my_type = type(obj_val).__name__
        if my_type in ['str', 'int', 'float', 'bool']:
            my_val = obj_val
        elif my_type == 'date':
            my_val = obj_val.strftime("%Y-%m-%d")
        elif my_type == 'datetime':
            my_val = obj_val.strftime("%Y-%m-%d %H:%M:%S")
        else:  # most likely a model
            if hasattr(obj_val, 'id'):
                if ContentType.objects.get_for_model(obj_val).name == 'enumerable type':
                    my_type = 'enumtypemodel'
                    my_val = obj_val.value
                else:
                    my_type = 'model'
                    my_val = obj_val.pk
            else:
                raise Exception("An invalid object was fed to the ConditionalMixin.val_type method!"
                                " ({0})".format(str(obj_val)))
        return my_val, my_type

    def set_value(self, obj_val, save=False):
        my_val, my_type = self.val_type(obj_val)

        self.value = json.dumps({"value": my_val, "type": my_type})
        if save:
            self.save(update_fields=['value'])

    @classmethod
    def mixin_check(cls):
        if not cls.group_field_name:
            raise Exception("ConditionalMixin requires a group field name which points to the foreign key field")

    @classmethod
    def build_filter(cls, model_instance):  # Not used by NotificationRuleConditions
        cls.mixin_check()

        filter_dict = {cls.group_field_name: model_instance}
        conditions = cls.get_models(**filter_dict).order_by('sort_ord')

        qs_filter = None
        for cnd in conditions:
            jd = json.loads(cnd.value)
            final_attr = "{0}__pk".format(cnd.attr) if jd['type'] == 'model' \
                else "{0}__{1}" if cnd.condition.value else cnd.attr  # empty condition.value means equals
            final_value = jd['value'] if jd['type'] in ['str', 'int', 'float', 'bool', 'model'] \
                else tz.date_from_string(jd['value']) if jd['type'] == 'date' \
                else tz.date_from_string(jd['value'], has_time=True) if jd['type'] == 'datetime' else None

            q = Q(**{final_attr: final_value})

            if not qs_filter:
                qs_filter = QSFilter(q)
            else:
                if cnd.group_prev:
                    if cnd.logical_and:
                        if cnd.negate:
                            qs_filter.grp_and(~q)
                        else:
                            qs_filter.grp_and(q)
                    else:
                        if cnd.negate:
                            qs_filter.grp_or(~q)
                        else:
                            qs_filter.grp_or(q)
                else:
                    if cnd.logical_and:
                        if cnd.negate:
                            qs_filter.x_and(~q)
                        else:
                            qs_filter.x_and(q)
                    else:
                        if cnd.negate:
                            qs_filter.x_or(~q)
                        else:
                            qs_filter.x_or(q)

        return qs_filter.f if qs_filter else None

    class Meta:
        abstract = True


class GenericRelationshipMixin:
    def set_generic_relation(self, model_obj, both: bool = False):
        from core.models import GenericModelRelationship
        rel1 = GenericModelRelationship.get_relation(model_obj, self)
        if not rel1:
            rel1 = GenericModelRelationship.add_relation(model_obj, self)
        if both:
            rel2 = GenericModelRelationship.get_relation(self, model_obj)
            if not rel2:
                rel2 = GenericModelRelationship.add_relation(self, model_obj)
        else:
            rel2 = False
        return rel1, rel2

    def clear_generic_relations(self, model):
        from core.models import GenericModelRelationship
        obj_relations = GenericModelRelationship.get_relations(self, model)
        if obj_relations:
            for rel in obj_relations:
                rel: GenericModelRelationship
                model_obj = rel.child()
                if model_obj:
                    # removes even a reverse relation
                    GenericModelRelationship.remove_relation(self, model_obj, both=True)


class XrefMixin:
    @classmethod
    def get_model_xref(cls, r_source_obj: Union['BaseModel', str, None] = None,
                       source_key=None, this_key=None, first_val=True, org_id=None):
        """
        If the data for this model is sourced/imported from an external database,
        store the external key for cross reference
        :param r_source_obj: The RecordSource object
        :param source_key: The external key value to find -- None if unknown
        :param this_key: Provided if only the internal key is known
        :param first_val: defaults to only return the first record found
        :param org_id: must be specified if there is no record source object, otherwise undefined results are given
        :return: ExternalXref instance
        """
        from core.models import RecordSource, ExternalXref
        filters = {'content_type': cls.get_content_type()}

        if type(r_source_obj) is RecordSource:
            r_source_obj: RecordSource
            filters['record_source_id'] = r_source_obj.id
        elif org_id:
            if r_source_obj and type(r_source_obj) is str:
                filters['record_source__value'] = str(r_source_obj)  # source value
                filters['record_source__organization_id'] = org_id
            else:
                filters['organization_id'] = org_id
        # else:  # if r_source_obj and type(r_source_obj) is str:
        #     # filters['record_source__value'] = r_source_obj
        #     print("WARNING: Record source object or source value and org are highly recommended.")

        if source_key:
            filters['source_id'] = str(source_key)
        elif this_key:
            filters['key'] = int(this_key)

        xr = ExternalXref.objects.filter(**filters)

        if first_val:
            return xr.first() if xr else None
        else:
            return xr if xr else None

    @classmethod
    def get_model_xref_instance(cls, r_source_obj, source_key=None, this_key=None, first_val=True):
        """
        Retrieve the internal instance of the record by referencing the external source
        :param r_source_obj: The RecordSource object
        :param source_key: The external key value to find
        :param this_key: The Agile record ID
        :param first_val: True/False return the first xref record that matches
        :return: an instance of the current model class -- None if not found
        """
        xr = None
        if source_key:
            xr = cls.get_model_xref(r_source_obj, source_key, first_val=first_val)
        else:
            xr = cls.get_model_xref(r_source_obj, this_key=this_key, first_val=first_val)

        if first_val:
            return xr.instance if xr else None
        else:
            return [xr_obj.instance for xr_obj in xr if xr_obj.instance] if xr else None

    def get_all_xref(self, r_source_obj=None, org_id=None) -> models.query.QuerySet:
        """
        Get all xref model objects that contain a reference to the current object.
        :return: QuerySet or None if there are no xref objects.
        """
        return self.get_model_xref(r_source_obj, this_key=self.id, first_val=False, org_id=org_id)

    def clear_xref(self, r_source_obj=None, org_id=None):
        """
        Delete all ExternalXref objects for the current record.
        :return: Nothing
        """
        xr_list = self.get_all_xref(r_source_obj, org_id)
        if xr_list:
            for xr in xr_list:
                xr.delete()

    def get_xref(self, r_source_obj: Union['BaseModel', str, None], first_val=True):
        """
        Get the ExternalXref records for the current record.
        :param r_source_obj: RecordSource object (set to null to find any that exist)
        :param first_val: Whether to get the first xref we find
        :return: QuerySet, or returns only first record if no source specified --
        can lead to unpredictable results
        """
        org_id = None
        if (not r_source_obj or type(r_source_obj) is str) and self.field_exists('organization'):
            org_id = self.required_org(None, self.organization_id) if self.organization_id else None
        return self.get_model_xref(r_source_obj, this_key=self.id, first_val=first_val, org_id=org_id)

    def get_xref_instance(self, r_source_obj):
        """
        Get the ExternalXref object for the current record.
        :param r_source_obj: RecordSource object
        :return: An ExternalXref object.
        """
        return self.get_model_xref_instance(r_source_obj, this_key=self.id)

    def make_model_xref(self, r_source_obj, source_key, set_updated_date=False, update_date=None):
        """
        Make an external reference for the current model instance
        :param r_source_obj: The RecordSource object
        :param source_key: The external key value to associate with the current record
        :param set_updated_date: change the date the external record was updated
        :param update_date: the date the external record was updated (if not set, will use current date)
        :return: ExternalXref instance
        """
        from core.models import ExternalXref

        if r_source_obj is None or type(r_source_obj) is str:
            raise Exception("Record Source object must be provided.")

        upd_or_create_params = {
            'record_source_id': r_source_obj.id,
            'organization_id': r_source_obj.organization.id,
            'source_id': source_key,
            'key': self.pk,
            'content_type': self.get_content_type()
        }
        if set_updated_date:
            if not update_date:
                update_date = tz.localtime()
            upd_or_create_params['ext_changed'] = update_date
        xr, updated, pre_data = ExternalXref.save_or_create_model(
            {'content_type': self.get_content_type(), 'record_source_id': r_source_obj.id,
             'organization_id': r_source_obj.organization.id, 'source_id': source_key},
            **upd_or_create_params)
        return xr

    @classmethod
    def external_model_create_or_diff(cls, org_id, record_source, source_id, obj_dict: dict,
                                      obj_create_dict: Optional[dict] = None, visual=False):
        """
        Create an external model including the xref record, ensure the xref exists for existing records, and/or return the model differences
        @param org_id: organization id
        @param record_source: the Record Source Object associated with the ExternalXref
        @param source_id: external identifier for this record
        @param obj_dict: the data for this model
        @param obj_create_dict: extra data to assign to the model that is not specified for comparison/update
        @param visual: show debug dots?
        @return: xref_dict_obj ({xr, obj_id}), obj_data ({obj, created, [data]}), xr_id
        """
        from core.logger import dot, ConsoleColors
        xr_update = None
        obj_data = None
        xr = cls.get_model_xref(record_source, source_id, org_id=org_id)
        if not xr or not xr.instance:
            if type(obj_create_dict) is dict:
                obj_dict.update(obj_create_dict)
            obj = cls.create_model(**obj_dict)
            if obj:
                if not xr:
                    xr = obj.make_model_xref(record_source, source_id)
                    if visual:
                        dot(color=ConsoleColors.GREEN)
                elif not xr.instance:
                    if visual:
                        dot(color=ConsoleColors.RED)
                    xr_update = {'xr': xr, 'obj_id': obj.id}
                obj_data = {'obj': obj, 'created': True}  # only returns differences
        else:
            obj = xr.instance
            upd_obj = obj.model_differences(obj_dict)
            if upd_obj:
                obj_data = {'obj': obj, 'data': upd_obj, 'created': False}
                if visual:
                    dot(color=ConsoleColors.MAGENTA)
            else:
                obj_data = {'obj': obj, 'created': False}
                if visual:
                    dot(color=ConsoleColors.CYAN)

        return xr_update, obj_data, xr.id if xr else None

    @classmethod
    def get_model_xref_list_from_pk_list(cls, source_value: str, pk_list: list, invert: bool = False):
        """
        Get all the external references to a list of model instance ids
        :param source_value: The name of the external source-- must match existing RecordSource value
        :param pk_list: list of pks
        :param invert: get anything NOT in this list
        :return: a list of ExternalXref objects -- empty list is returned if none are found
        """
        from core.models import ExternalXref, QSFilter, Q
        qs_f = QSFilter(Q(source=source_value) & Q(content_type=cls.get_content_type()))
        if invert:
            qs_f.x_and(~Q(pk__in=pk_list))
        else:
            qs_f.x_and(Q(pk__in=pk_list))
        xr_list = ExternalXref.objects.filter(qs_f.filter)
        return list(xr_list) if xr_list else []