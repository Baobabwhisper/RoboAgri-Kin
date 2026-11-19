from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

PCT = [MinValueValidator(0), MaxValueValidator(100)]

#
# 1. Référentiel agricole
#

class Parcelle(models.Model):
    code = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=100)
    localisation = models.CharField(max_length=200, blank=True)
    superficie_m2 = models.FloatField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(superficie_m2__isnull=True) | Q(superficie_m2__gt=0),
                name="parcelle_superficie_positive"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.nom}"


class Zone(models.Model):
    parcelle = models.ForeignKey(Parcelle, on_delete=models.PROTECT, related_name="zones")
    code = models.CharField(max_length=20)
    nom = models.CharField(max_length=100, blank=True)
    pos_x_cm = models.FloatField(null=True, blank=True)
    pos_y_cm = models.FloatField(null=True, blank=True)
    seuil_min_pct = models.FloatField(default=30, validators=PCT)
    actif = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parcelle", "code"], name="zone_code_unique_par_parcelle"),
            models.CheckConstraint(
                condition=Q(seuil_min_pct__gte=0, seuil_min_pct__lte=100),
                name="zone_seuil_0_100"
            ),
        ]

    def __str__(self):
        return f"{self.parcelle.code}/{self.code}"


class Culture(models.Model):
    class Besoin(models.TextChoices):
        FAIBLE = "FAIBLE"
        MOYEN = "MOYEN"
        ELEVE = "ELEVE"

    nom = models.CharField(max_length=100, unique=True)
    nom_scientifique = models.CharField(max_length=150, blank=True)
    besoin_eau = models.CharField(max_length=10, choices=Besoin.choices, blank=True)

    def __str__(self):
        return self.nom


class Plantation(models.Model):
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="plantations")
    culture = models.ForeignKey(Culture, on_delete=models.PROTECT, related_name="plantations")
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(date_fin__isnull=True) | Q(date_fin__gte=F("date_debut")),
                name="plantation_dates_coherentes"
            ),
            models.UniqueConstraint(
                fields=["zone"],
                condition=Q(date_fin__isnull=True),
                name="plantation_une_active_par_zone"
            ),
        ]


#
# 2. Matériel et étalonnage
#

class Robot(models.Model):
    class Statut(models.TextChoices):
        HORS_LIGNE = "HORS_LIGNE"
        DISPONIBLE = "DISPONIBLE"
        EN_MISSION = "EN_MISSION"
        ERREUR = "ERREUR"

    identifiant = models.CharField(max_length=50, unique=True)
    nom = models.CharField(max_length=100, blank=True)
    statut = models.CharField(max_length=15, choices=Statut.choices, default=Statut.HORS_LIGNE)
    derniere_connexion = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.identifiant


class Capteur(models.Model):
    class Type(models.TextChoices):
        HUMIDITE_SOL = "HUMIDITE_SOL"
        DISTANCE = "DISTANCE"

    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name="capteurs")
    type_capteur = models.CharField(max_length=15, choices=Type.choices)
    reference = models.CharField(max_length=100)
    actif = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["robot", "reference"], name="capteur_ref_unique_par_robot"),
        ]

    def __str__(self):
        return f"{self.type_capteur} ({self.reference})"


class Etalonnage(models.Model):
    capteur = models.ForeignKey(Capteur, on_delete=models.PROTECT, related_name="etalonnages")
    brut_sec = models.IntegerField()
    brut_humide = models.IntegerField()
    methode = models.TextField()
    date_etalonnage = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(brut_sec=F("brut_humide")), name="etalonnage_bornes_distinctes"),
            models.UniqueConstraint(
                fields=["capteur"],
                condition=Q(actif=True),
                name="etalonnage_un_actif_par_capteur"
            ),
        ]

    def humidite_pct(self, brut):
        pct = (brut - self.brut_sec) / (self.brut_humide - self.brut_sec) * 100
        return max(0.0, min(100.0, pct))


class ParametreSysteme(models.Model):
    cle = models.CharField(max_length=50, primary_key=True)
    valeur = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.cle}={self.valeur}"


#
# 3. Missions
#

class Mission(models.Model):
    class Statut(models.TextChoices):
        PLANIFIEE = "PLANIFIEE"
        EN_COURS = "EN_COURS"
        TERMINEE = "TERMINEE"
        INTERROMPUE = "INTERROMPUE"
        NON_CONFIRMEE = "NON_CONFIRMEE"
        ANNULEE = "ANNULEE"

    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name="missions")
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    statut = models.CharField(max_length=15, choices=Statut.choices, default=Statut.PLANIFIEE)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    motif_fin = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(date_fin__isnull=True) | Q(date_debut__isnull=True) | Q(date_fin__gte=F("date_debut")),
                name="mission_dates_coherentes"
            ),
            models.CheckConstraint(
                condition=Q(date_fin__isnull=False) | ~Q(statut__in=["TERMINEE", "INTERROMPUE"]),
                name="mission_cloturee_a_une_date_fin"
            ),
        ]

    def __str__(self):
        return f"Mission #{self.pk} ({self.statut})"


class EtapeMission(models.Model):
    class Statut(models.TextChoices):
        A_FAIRE = "A_FAIRE"
        EN_COURS = "EN_COURS"
        FAITE = "FAITE"
        IGNOREE = "IGNOREE"
        ECHEC = "ECHEC"

    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="etapes")
    ordre = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="etapes")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.A_FAIRE)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["mission", "ordre"]
        constraints = [
            models.UniqueConstraint(fields=["mission", "ordre"], name="etape_ordre_unique"),
            models.UniqueConstraint(fields=["mission", "zone"], name="etape_zone_unique_par_mission"),
            models.CheckConstraint(condition=Q(ordre__gte=1), name="etape_ordre_positif"),
        ]


#
# 4. Mesures
#

class Mesure(models.Model):
    class Validite(models.TextChoices):
        VALIDE = "VALIDE"
        INVALIDE = "INVALIDE"
        INCOHERENTE = "INCOHERENTE"
        MANQUANTE = "MANQUANTE"

    message_uid = models.CharField(max_length=64)
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name="mesures")
    capteur = models.ForeignKey(Capteur, on_delete=models.PROTECT, related_name="mesures")
    etalonnage = models.ForeignKey(Etalonnage, null=True, blank=True, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name="mesures")
    etape = models.ForeignKey(EtapeMission, on_delete=models.PROTECT, related_name="mesures")
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="mesures")
    numero_sequence = models.PositiveIntegerField(null=True, blank=True)
    valeur_brute = models.IntegerField(null=True, blank=True)
    humidite_pct = models.FloatField(null=True, blank=True)
    validite = models.CharField(max_length=12, choices=Validite.choices, default=Validite.VALIDE)
    motif_invalidite = models.CharField(max_length=255, blank=True)
    horodatage_mesure = models.DateTimeField()
    horodatage_reception = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["zone", "horodatage_mesure"], name="ix_mesure_zone_date")]
        constraints = [
            models.UniqueConstraint(fields=["robot", "message_uid"], name="mesure_message_unique"),
            models.CheckConstraint(
                condition=Q(validite="VALIDE", humidite_pct__isnull=False, humidite_pct__gte=0, humidite_pct__lte=100) | ~Q(validite="VALIDE"),
                name="mesure_valide_pct_0_100"
            ),
            models.CheckConstraint(
                condition=Q(validite="VALIDE") | Q(motif_invalidite__gt=""),
                name="mesure_invalide_a_un_motif"
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.etape_id and (self.etape.zone_id != self.zone_id or self.etape.mission_id != self.mission_id):
            raise ValidationError("La zone/mission de la mesure ne correspond pas à l'étape.")


#
# 5. Décision et irrigation
#

class DecisionIrrigation(models.Model):
    class Decision(models.TextChoices):
        AUCUNE_ACTION = "AUCUNE_ACTION"
        RECOMMANDE = "ARROSAGE_RECOMMANDE"
        AUTORISE = "ARROSAGE_AUTORISE"
        INTERDIT = "INTERDIT"

    mesure = models.OneToOneField(Mesure, on_delete=models.PROTECT, related_name="decision")
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="decisions")
    seuil_utilise_pct = models.FloatField(validators=PCT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    motif = models.CharField(max_length=255, blank=True)
    date_decision = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.zone} : {self.decision}"



class Irrigation(models.Model):
    class Statut(models.TextChoices):
        DEMANDEE = "DEMANDEE"
        EN_COURS = "EN_COURS"
        TERMINEE = "TERMINEE"
        ECHOUEE = "ECHOUEE"
        ARRETEE_SECURITE = "ARRETEE_SECURITE"

    commande_uid = models.CharField(max_length=64, unique=True)
    decision = models.ForeignKey(DecisionIrrigation, on_delete=models.PROTECT, related_name="irrigations")
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="irrigations")
    mission = models.ForeignKey(Mission, null=True, blank=True, on_delete=models.PROTECT, related_name="irrigations")
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name="irrigations")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.DEMANDEE)
    duree_max_s = models.PositiveSmallIntegerField()
    duree_reelle_s = models.PositiveSmallIntegerField(null=True, blank=True)
    volume_ml = models.FloatField(null=True, blank=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(duree_max_s__gte=1, duree_max_s__lte=60),
                name="irrigation_duree_max_1_60s"
            ),
            models.CheckConstraint(
                condition=Q(duree_reelle_s__isnull=True) | Q(duree_reelle_s__lte=F("duree_max_s")),
                name="irrigation_duree_reelle_sous_plafond"
            ),
            models.CheckConstraint(
                condition=Q(volume_ml__isnull=True) | Q(volume_ml__gte=0),
                name="irrigation_volume_positif"
            ),
        ]


#
# 6. Incidents et journal de communication
#

class Incident(models.Model):
    class Type(models.TextChoices):
        OBSTACLE = "OBSTACLE"
        MESURE_INVALIDE = "MESURE_INVALIDE"
        CAPTEUR_DEFAILLANT = "CAPTEUR_DEFAILLANT"
        COMM_PERDUE = "COMM_PERDUE"
        BATTERIE_FAIBLE = "BATTERIE_FAIBLE"
        POMPE = "POMPE"
        MISSION_NON_CONFIRMEE = "MISSION_NON_CONFIRMEE"
        AUTRE = "AUTRE"

    class Gravite(models.TextChoices):
        FAIBLE = "FAIBLE"
        MOYENNE = "MOYENNE"
        CRITIQUE = "CRITIQUE"

    class Statut(models.TextChoices):
        OUVERT = "OUVERT"
        EN_COURS = "EN_COURS"
        RESOLU = "RESOLU"

    type_incident = models.CharField(max_length=25, choices=Type.choices)
    gravite = models.CharField(max_length=10, choices=Gravite.choices, default=Gravite.MOYENNE)
    robot = models.ForeignKey(Robot, null=True, blank=True, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, null=True, blank=True, on_delete=models.PROTECT)
    zone = models.ForeignKey(Zone, null=True, blank=True, on_delete=models.PROTECT)
    mesure = models.ForeignKey(Mesure, null=True, blank=True, on_delete=models.PROTECT)
    irrigation = models.ForeignKey(Irrigation, null=True, blank=True, on_delete=models.PROTECT)
    description = models.TextField()
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.OUVERT)
    date_incident = models.DateTimeField(default=timezone.now)
    date_resolution = models.DateTimeField(null=True, blank=True)
    resolu_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="incidents_resolus")

    class Meta:
        indexes = [models.Index(fields=["statut", "date_incident"], name="ix_incident_statut")]
        constraints = [
            models.CheckConstraint(
                condition=Q(statut__in=["OUVERT", "EN_COURS"]) | Q(date_resolution__isnull=False),
                name="incident_resolu_a_une_date"
            ),
        ]


class MessageCommunication(models.Model):
    class Direction(models.TextChoices):
        APP_VERS_ROBOT = "APP_VERS_ROBOT"
        ROBOT_VERS_APP = "ROBOT_VERS_APP"

    message_uid = models.CharField(max_length=64)
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name="messages")
    mission = models.ForeignKey(Mission, null=True, blank=True, on_delete=models.PROTECT)
    direction = models.CharField(max_length=15, choices=Direction.choices)
    type_message = models.CharField(max_length=30)
    payload = models.JSONField()
    date_message = models.DateTimeField(auto_now_add=True)
    traite = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["robot", "direction", "message_uid"], name="message_unique_par_robot_direction"),
        ]
