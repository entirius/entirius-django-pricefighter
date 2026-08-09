# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_pricefighter.models import Channel, PricingRule, ProductRepresentation, QuoteConfig
from django_pricefighter.services import channel_sync_service


@admin.action(description="Sync channels from PIM")
def sync_channels_from_pim(modeladmin, request, queryset):
    count = channel_sync_service.sync_channels_from_pim()
    modeladmin.message_user(request, f"Synced {count} channels from PIM.")


class ChannelAdmin(admin.ModelAdmin):
    list_display = ("idx", "name", "default_language")
    search_fields = ["idx", "name"]
    actions = [sync_channels_from_pim]


class ProductRepresentationAdmin(admin.ModelAdmin):
    list_display = ("sku", "channel", "name", "category", "is_active")
    list_filter = ("channel", "is_active")
    search_fields = ["sku", "name"]


class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "strategy", "mode", "price_war", "channel")
    list_filter = ("strategy", "mode", "price_war")
    search_fields = ["sku", "category_idx"]

    def save_model(self, request, obj, form, change) -> None:
        obj.full_clean()
        super().save_model(request, obj, form, change)


class QuoteConfigAdmin(admin.ModelAdmin):
    list_display = ("currency", "range_from", "range_to", "band_dn", "band_up", "undercut", "rounding")
    list_filter = ("currency", "rounding")
    ordering = ("currency", "range_from")

    def save_model(self, request, obj, form, change) -> None:
        obj.full_clean()
        super().save_model(request, obj, form, change)


admin.site.register(Channel, ChannelAdmin)
admin.site.register(ProductRepresentation, ProductRepresentationAdmin)
admin.site.register(PricingRule, PricingRuleAdmin)
admin.site.register(QuoteConfig, QuoteConfigAdmin)
