{{- define "boomarr.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "boomarr.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "boomarr.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "boomarr.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "boomarr.selectorLabels" -}}
app.kubernetes.io/name: {{ include "boomarr.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "boomarr.configMapName" -}}
{{- default (include "boomarr.fullname" .) .Values.existingConfigMap }}
{{- end }}

{{- define "boomarr.secretName" -}}
{{- default (include "boomarr.fullname" .) .Values.webhook.existingSecret }}
{{- end }}

{{/* Render the Boomarr config, injecting the webhook trigger when enabled. */}}
{{- define "boomarr.config" -}}
{{- $cfg := deepCopy .Values.config }}
{{- if .Values.webhook.enabled }}
{{- $triggers := list }}
{{- if hasKey $cfg "triggers" }}
{{- $triggers = $cfg.triggers }}
{{- else }}
{{- $triggers = list (dict "type" "schedule") }}
{{- end }}
{{- $_ := set $cfg "triggers" (append $triggers (dict "type" "webhook" "port" .Values.webhook.port)) }}
{{- end }}
{{- toYaml $cfg }}
{{- end }}
