from typing import Optional, Dict, Type

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import ForeignKey, QuerySet

from mixins import BaseModel, AutoDateAndSourceMixin


class GenericModelRelationship(AutoDateAndSourceMixin):
    """
    Relations must be extended from BaseModel.
    Not meant to be used extensively. POTENTIALLY SLOW-- Don't use when generating lists (for a parent).
    """
    rel = "generic_relation"
    parent_relation = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name=f"{rel}_parent")
    parent_model_id = models.IntegerField("The parent model's id")
    child_relation = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name=f"{rel}_child")
    child_model_id = models.IntegerField("The child model's id")

    def parent(self):
        self.parent_relation: ContentType
        return self.parent_relation.model_class().by_id(self.parent_model_id)

    def child(self):
        self.child_relation: ContentType
        return self.child_relation.model_class().by_id(self.child_model_id)

    @classmethod
    def add_relation(cls, parent_obj: Optional[BaseModel], child_obj: Optional[BaseModel]):
        parent_type = parent_obj.get_content_type()
        child_type = child_obj.get_content_type()
        if parent_type and child_type:
            return cls.create_model(**{
                'parent_relation_id': parent_type.id,
                'parent_model_id': parent_obj.id,
                'child_relation_id': child_type.id,
                'child_model_id': child_obj.id
            })
        return None

    @classmethod
    def add_relation_by_id(cls, parent_obj: Optional[BaseModel], child_class: Type[BaseModel], child_id: int):
        parent_type = parent_obj.get_content_type()
        child_type = child_class.get_content_type()
        if parent_type and child_type:
            return cls.create_model(**{
                'parent_relation_id': parent_type.id,
                'parent_model_id': parent_obj.id,
                'child_relation_id': child_type.id,
                'child_model_id': child_id
            })
        return None

    @classmethod
    def get_relation_by_id(cls, parent_obj: Optional[BaseModel], child_class: Type[BaseModel], child_id: int):
        parent_type = parent_obj.get_content_type()
        child_type = child_class.get_content_type()
        if parent_type and child_type:
            return cls.get(**{'parent_relation_id': parent_type.id,
                              'parent_model_id': parent_obj.id,
                              'child_relation_id': child_type.id,
                              'child_model_id': child_id
                              })
        return None

    @classmethod
    def get_relation(cls, parent_obj: Optional[BaseModel], child_obj: Optional[BaseModel]):
        parent_type = parent_obj.get_content_type()
        child_type = child_obj.get_content_type()
        if parent_type and child_type:
            return cls.get(**{'parent_relation_id': parent_type.id,
                                 'parent_model_id': parent_obj.id,
                                 'child_relation_id': child_type.id,
                                 'child_model_id': child_obj.id
                              })
        return None

    @classmethod
    def remove_relation(cls, parent_obj: Optional[BaseModel], child_obj: Optional[BaseModel], both: bool = False) -> bool:
        parent_type = parent_obj.get_content_type()
        child_type = child_obj.get_content_type()
        removed = False
        if parent_type and child_type:
            obj = cls.get_relation(parent_obj, child_obj)
            if obj:
                obj.delete()
                removed = True
            if both:
                obj = cls.get_relation(child_obj, parent_obj)
                if obj:
                    obj.delete()
                    removed = True
        return removed

    @classmethod
    def remove_relation_by_id(cls, parent_obj: Optional[BaseModel], child_class: Type[BaseModel], child_id: int) -> bool:
        parent_type = parent_obj.get_content_type()
        child_type = child_class.get_content_type()
        if parent_type and child_type:
            obj = cls.get_relation_by_id(parent_obj, child_class, child_id)
            if obj:
                obj.delete()
                return True
        return False

    @classmethod
    def get_relations(cls, parent_obj: Optional[BaseModel], child_class: Type[BaseModel]) -> Optional[QuerySet]:
        parent_type = parent_obj.get_content_type()
        child_type = child_class.get_content_type()
        if parent_type:
            return cls.filter(**{'parent_relation_id': parent_type.id,
                                 'parent_model_id': parent_obj.id, 'child_relation_id': child_type.id})
        return None

    @classmethod
    def get_reverse_relations(cls, child_obj: Optional[BaseModel], parent_class: Type[BaseModel]) -> Optional[QuerySet]:
        parent_type = parent_class.get_content_type()
        child_type = child_obj.get_content_type()
        if parent_type:
            return cls.filter(**{'parent_relation_id': parent_type.id,
                                 'child_model_id': child_obj.id, 'child_relation_id': child_type.id})
        return None

    @classmethod
    def get_relation_list(cls, parent_obj: Optional[BaseModel], child_class: Type[BaseModel],
                          add_obj: Optional[BaseModel] = None) -> list:
        rels = cls.get_relations(parent_obj, child_class)
        return cls.check_relations(rels, add_obj)

    @classmethod
    def get_reverse_relation_list(cls, child_obj: Optional[BaseModel], parent_class: Type[BaseModel],
                                  add_obj: Optional[BaseModel] = None) -> list:
        rels = cls.get_reverse_relations(child_obj, parent_class)
        return cls.check_relations(rels, add_obj)

    @staticmethod
    def check_relations(rels, add_obj: Optional[BaseModel] = None):
        rel_list = []
        if rels:
            for rel in rels:
                child = rel.child
                if child and child.id not in [r.id for r in rel_list]:
                    rel_list.append(child)
        if add_obj and add_obj.id not in [r.id for r in rel_list]:
            rel_list.append(add_obj)
        return rel_list

    @classmethod
    def get_all_relations(cls, parent_obj: Optional[BaseModel]) -> Optional[QuerySet]:
        parent_type = parent_obj.get_content_type()
        if parent_type:
            return cls.filter(**{'parent_relation_id': parent_type.id,
                                 'parent_model_id': parent_obj.id})
        return None

    @classmethod
    def get_sorted_relations(cls, parent_obj: Optional[BaseModel]) -> Dict[ForeignKey, list]:
        relations = {}
        rels = cls.get_all_relations(parent_obj)
        if rels:
            for r in rels:
                r: GenericModelRelationship
                if r.child_relation not in relations.keys():
                    relations[r.child_relation] = []
                relations[r.child_relation].append(r.child)
        return relations

    class Meta(BaseModel.Meta):
        abstract = True
        # db_table = 'core_generic_relation'
        # indexes = [
        #     models.Index(fields=['parent_relation', 'parent_model_id', 'child_relation'], name=f'gr_idx_child'),
        #     models.Index(fields=['parent_relation', 'parent_model_id'], name=f'gr_idx_parent'),
        #     models.Index(fields=['parent_relation', 'child_model_id', 'child_relation'], name=f'gr_idx_child_mod'),
        # ]
        # unique_together = (('parent_relation', 'parent_model_id', 'child_relation', 'child_model_id'),)
