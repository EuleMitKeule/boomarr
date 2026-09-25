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
{{- default (include "boomarr.fullname" .) .Values.server.existingSecret }}
{{- end }}

{{/* Render the Boomarr config, enabling the HTTP server when requested. */}}
{{- define "boomarr.config" -}}
{{- $cfg := deepCopy .Values.config }}
{{- if .Values.server.enabled }}
{{- $server := dict "enabled" true "port" .Values.server.port "metrics_auth" .Values.server.metricsAuth }}
{{- $_ := set $cfg "server" (merge $server (default (dict) $cfg.server)) }}
{{- end }}
{{- toYaml $cfg }}
{{- end }}
