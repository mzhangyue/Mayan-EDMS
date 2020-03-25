from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext_lazy as _

from mayan.apps.common.signals import signal_mayan_pre_save
from mayan.apps.documents.events import event_document_create
from mayan.apps.documents.models import Document, DocumentVersion
from mayan.apps.user_management.querysets import get_user_queryset

from .classes import QuotaBackend
from .exceptions import QuotaExceeded
from .mixins import DocumentTypesQuotaMixin, GroupsUsersQuotaMixin


class DocumentCountQuota(
    GroupsUsersQuotaMixin, DocumentTypesQuotaMixin, QuotaBackend
):
    error_message = _('Document count quota exceeded.')
    field_order = ('documents_limit',)
    fields = {
        'documents_limit': {
            'label': _('Documents limit'),
            'class': 'django.forms.IntegerField',
            'help_text': _(
                'Maximum number of documents.'
            )
        },
    }
    label = _('Document count limit')
    sender = Document
    signal = signal_mayan_pre_save

    def __init__(
        self, document_type_all, document_type_ids, documents_limit,
        group_ids, user_all, user_ids
    ):
        self.document_type_all = document_type_all
        self.document_type_ids = document_type_ids
        self.documents_limit = documents_limit
        self.group_ids = group_ids
        self.user_all = user_all
        self.user_ids = user_ids

    def _allowed(self):
        return self.documents_limit

    def _allowed_filter_display(self):
        return _('document count: %(document_count)s') % {
            'document_count': self._allowed()
        }

    def _get_user_document_count(self, user):
        filter_kwargs = {
            'target_actions__verb': event_document_create.id
        }

        if not self.document_type_all:
            filter_kwargs.update(
                {
                    'document_type_id__in': self._get_document_types().values(
                        'pk'
                    ),
                }
            )

        if user:
            # Admins are always excluded
            if user.is_superuser or user.is_staff:
                return 0

            if not self.user_all:
                users = self._get_users() | get_user_queryset().filter(
                    groups__in=self._get_groups()
                )

                if not users.filter(pk=user.pk).exists():
                    return 0

            content_type = ContentType.objects.get_for_model(
                model=get_user_model()
            )

            filter_kwargs.update(
                {
                    'target_actions__actor_object_id': user.pk,
                    'target_actions__actor_content_type': content_type,
                }
            )

        return Document.objects.filter(**filter_kwargs).count()

    def process(self, **kwargs):
        # Only for new documents
        if not kwargs['instance'].pk:
            if self._get_user_document_count(user=kwargs.get('user')) >= self._allowed():
                raise QuotaExceeded(
                    _('Document size quota exceeded.')
                )


class DocumentSizeQuota(
    GroupsUsersQuotaMixin, DocumentTypesQuotaMixin, QuotaBackend
):
    field_order = ('document_size_limit',)
    fields = {
        'document_size_limit': {
            'label': _('Document size limit'),
            'class': 'django.forms.FloatField',
            'help_text': _('Maximum document size in megabytes (MB).')
        }
    }
    label = _('Document size limit')
    sender = DocumentVersion
    signal = signal_mayan_pre_save

    def __init__(
        self, document_size_limit, document_type_all, document_type_ids,
        group_ids, user_all, user_ids
    ):
        self.document_size_limit = document_size_limit
        self.document_type_all = document_type_all
        self.document_type_ids = document_type_ids
        self.group_ids = group_ids
        self.user_all = user_all
        self.user_ids = user_ids

    def _allowed(self):
        return self.document_size_limit * 1024 * 1024

    def _allowed_filter_display(self):
        return _('document size: %(formatted_file_size)s') % {
            'formatted_file_size': filesizeformat(self._allowed())
        }

    def process(self, **kwargs):
        if not kwargs['instance'].pk:
            if kwargs['instance'].file.size >= self._allowed():
                if self.document_type_all or self._get_document_types().filter(pk=kwargs['instance'].document.document_type.pk).exists():
                    # Don't asume there is always a user in the signal.
                    # Non interactive uploads might not include a user.
                    if kwargs['user']:
                        if kwargs['user'].is_superuser or kwargs['user'].is_staff:
                            return

                    users = self._get_users() | get_user_queryset().filter(
                        groups__in=self._get_groups()
                    )

                    if self.user_all or kwargs['user'] and users.filter(pk=kwargs['user'].pk).exists():
                        raise QuotaExceeded(
                            _('Document size quota exceeded.')
                        )
