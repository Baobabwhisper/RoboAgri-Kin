from django.contrib import admin
 
from . import models as m
 
 
@admin.register(m.Mesure)
class MesureAdmin(admin.ModelAdmin):
    list_display = ("id", "zone", "mission", "humidite_pct", "validite", "horodatage_mesure")
    list_filter = ("validite", "zone")
    date_hierarchy = "horodatage_mesure"
 
    def has_change_permission(self, request, obj=None):
        return False  # mesures immuables (trigger trg_mesure_immuable)
 
 
@admin.register(m.Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("id", "robot", "statut", "date_debut", "date_fin")
    list_filter = ("statut", "robot")
 
 
@admin.register(m.Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("code", "parcelle", "seuil_min_pct", "actif")
 
 
@admin.register(m.Irrigation)
class IrrigationAdmin(admin.ModelAdmin):
    list_display = ("commande_uid", "zone", "statut", "duree_max_s", "duree_reelle_s", "volume_ml")
 
 
@admin.register(m.Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("type_incident", "gravite", "statut", "zone", "date_incident")
    list_filter = ("statut", "gravite", "type_incident")
 
 
for model in (m.Parcelle, m.Culture, m.Plantation, m.Robot, m.Capteur, m.Etalonnage,
              m.ParametreSysteme, m.EtapeMission, m.DecisionIrrigation, m.MessageCommunication):
    admin.site.register(model)
 