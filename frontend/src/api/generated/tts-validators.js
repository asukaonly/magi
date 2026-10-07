// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateSynthesisJob = validate53;
const schema20 = {"properties":{"cleaner_version":{"default":"1","title":"Cleaner Version","type":"string"},"content_hash":{"title":"Content Hash","type":"string"},"engine":{"title":"Engine","type":"string"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"expires_at":{"title":"Expires At","type":"number"},"job_id":{"title":"Job Id","type":"string"},"model":{"title":"Model","type":"string"},"ready_segments":{"default":0,"title":"Ready Segments","type":"integer"},"request_id":{"title":"Request Id","type":"string"},"speed":{"title":"Speed","type":"number"},"state":{"enum":["ready","running","completed","cancelling","cancelled","failed","unknown"],"title":"State","type":"string"},"total_segments":{"title":"Total Segments","type":"integer"},"voice":{"title":"Voice","type":"string"}},"required":["job_id","request_id","state","engine","model","voice","speed","content_hash","cleaner_version","total_segments","ready_segments","expires_at","error"],"title":"SynthesisJob","type":"object"};

function validate53(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate53.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((((data.job_id === undefined) && (missing0 = "job_id")) || ((data.request_id === undefined) && (missing0 = "request_id"))) || ((data.state === undefined) && (missing0 = "state"))) || ((data.engine === undefined) && (missing0 = "engine"))) || ((data.model === undefined) && (missing0 = "model"))) || ((data.voice === undefined) && (missing0 = "voice"))) || ((data.speed === undefined) && (missing0 = "speed"))) || ((data.content_hash === undefined) && (missing0 = "content_hash"))) || ((data.cleaner_version === undefined) && (missing0 = "cleaner_version"))) || ((data.total_segments === undefined) && (missing0 = "total_segments"))) || ((data.ready_segments === undefined) && (missing0 = "ready_segments"))) || ((data.expires_at === undefined) && (missing0 = "expires_at"))) || ((data.error === undefined) && (missing0 = "error"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cleaner_version !== undefined){
const _errs1 = errors;
if(typeof data.cleaner_version !== "string"){
validate53.errors = [{instancePath:instancePath+"/cleaner_version",schemaPath:"#/properties/cleaner_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.content_hash !== undefined){
const _errs3 = errors;
if(typeof data.content_hash !== "string"){
validate53.errors = [{instancePath:instancePath+"/content_hash",schemaPath:"#/properties/content_hash/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.engine !== undefined){
const _errs5 = errors;
if(typeof data.engine !== "string"){
validate53.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data3 = data.error;
const _errs7 = errors;
const _errs8 = errors;
let valid1 = false;
const _errs9 = errors;
if(typeof data3 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs9 === errors;
valid1 = valid1 || _valid0;
const _errs11 = errors;
if(data3 !== null){
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs11 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.expires_at !== undefined){
const _errs13 = errors;
if(!(typeof data.expires_at == "number")){
validate53.errors = [{instancePath:instancePath+"/expires_at",schemaPath:"#/properties/expires_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.job_id !== undefined){
const _errs15 = errors;
if(typeof data.job_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/job_id",schemaPath:"#/properties/job_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model !== undefined){
const _errs17 = errors;
if(typeof data.model !== "string"){
validate53.errors = [{instancePath:instancePath+"/model",schemaPath:"#/properties/model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ready_segments !== undefined){
let data7 = data.ready_segments;
const _errs19 = errors;
if(!((typeof data7 == "number") && (!(data7 % 1) && !isNaN(data7)))){
validate53.errors = [{instancePath:instancePath+"/ready_segments",schemaPath:"#/properties/ready_segments/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.request_id !== undefined){
const _errs21 = errors;
if(typeof data.request_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speed !== undefined){
const _errs23 = errors;
if(!(typeof data.speed == "number")){
validate53.errors = [{instancePath:instancePath+"/speed",schemaPath:"#/properties/speed/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data10 = data.state;
const _errs25 = errors;
if(typeof data10 !== "string"){
validate53.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data10 === "ready") || (data10 === "running")) || (data10 === "completed")) || (data10 === "cancelling")) || (data10 === "cancelled")) || (data10 === "failed")) || (data10 === "unknown"))){
validate53.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema20.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_segments !== undefined){
let data11 = data.total_segments;
const _errs27 = errors;
if(!((typeof data11 == "number") && (!(data11 % 1) && !isNaN(data11)))){
validate53.errors = [{instancePath:instancePath+"/total_segments",schemaPath:"#/properties/total_segments/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.voice !== undefined){
const _errs29 = errors;
if(typeof data.voice !== "string"){
validate53.errors = [{instancePath:instancePath+"/voice",schemaPath:"#/properties/voice/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"cleaner_version":true,"content_hash":true,"engine":true,"error":true,"expires_at":true,"job_id":true,"model":true,"ready_segments":true,"request_id":true,"speed":true,"state":true,"total_segments":true,"voice":true},"dynamicProps":false,"dynamicItems":false};

export const validateTTSConfiguration = validate54;
const schema21 = {"properties":{"models":{"items":{"$ref":"#/components/schemas/TTSModelChoice"},"title":"Models","type":"array"},"revision":{"title":"Revision","type":"string"},"settings":{"$ref":"#/components/schemas/TTSSettings"}},"required":["settings","revision","models"],"title":"TTSConfiguration","type":"object"};
const schema22 = {"properties":{"custom_model":{"default":false,"title":"Custom Model","type":"boolean"},"custom_voice":{"default":false,"title":"Custom Voice","type":"boolean"},"download_bytes":{"default":0,"title":"Download Bytes","type":"integer"},"emotions":{"items":{"type":"string"},"title":"Emotions","type":"array"},"engine":{"enum":["local","remote"],"title":"Engine","type":"string"},"instructions":{"default":false,"title":"Instructions","type":"boolean"},"model_id":{"title":"Model Id","type":"string"},"name":{"title":"Name","type":"string"},"provider_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Provider Id"},"provider_name":{"default":"","title":"Provider Name","type":"string"},"speed_max":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Speed Max"},"speed_min":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Speed Min"},"status":{"anyOf":[{"$ref":"#/components/schemas/TTSModelStatus"},{"type":"null"}],"default":null},"voices":{"items":{"$ref":"#/components/schemas/VoiceInfo"},"title":"Voices","type":"array"}},"required":["engine","model_id","name","provider_id","provider_name","voices","custom_voice","custom_model","speed_min","speed_max","instructions","emotions","download_bytes","status"],"title":"TTSModelChoice","type":"object"};
const schema23 = {"properties":{"download":{"anyOf":[{"$ref":"#/components/schemas/DownloadProgress"},{"type":"null"}],"default":null},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"model_id":{"default":"kokoro-multi-lang-v1_0","title":"Model Id","type":"string"},"recommended":{"default":false,"title":"Recommended","type":"boolean"},"runtime_available":{"default":false,"title":"Runtime Available","type":"boolean"},"state":{"default":"missing","enum":["missing","downloading","ready","failed","cancelled"],"title":"State","type":"string"}},"required":["model_id","state","download","error","runtime_available","recommended"],"title":"TTSModelStatus","type":"object"};
const schema24 = {"properties":{"downloaded_bytes":{"default":0,"minimum":0,"title":"Downloaded Bytes","type":"integer"},"eta_seconds":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Eta Seconds"},"files_completed":{"default":0,"minimum":0,"title":"Files Completed","type":"integer"},"phase":{"default":"connecting","enum":["connecting","downloading","retrying","verifying","completed","cancelled","failed"],"title":"Phase","type":"string"},"speed_bps":{"default":0,"minimum":0,"title":"Speed Bps","type":"number"},"total_bytes":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Total Bytes"},"total_files":{"default":0,"minimum":0,"title":"Total Files","type":"integer"}},"required":["phase","downloaded_bytes","total_bytes","speed_bps","eta_seconds","files_completed","total_files"],"title":"DownloadProgress","type":"object"};

function validate57(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate57.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.phase === undefined) && (missing0 = "phase")) || ((data.downloaded_bytes === undefined) && (missing0 = "downloaded_bytes"))) || ((data.total_bytes === undefined) && (missing0 = "total_bytes"))) || ((data.speed_bps === undefined) && (missing0 = "speed_bps"))) || ((data.eta_seconds === undefined) && (missing0 = "eta_seconds"))) || ((data.files_completed === undefined) && (missing0 = "files_completed"))) || ((data.total_files === undefined) && (missing0 = "total_files"))){
validate57.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.downloaded_bytes !== undefined){
let data0 = data.downloaded_bytes;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate57.errors = [{instancePath:instancePath+"/downloaded_bytes",schemaPath:"#/properties/downloaded_bytes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
validate57.errors = [{instancePath:instancePath+"/downloaded_bytes",schemaPath:"#/properties/downloaded_bytes/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.eta_seconds !== undefined){
let data1 = data.eta_seconds;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(errors === _errs5){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
const err0 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
else {
const err1 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs7 = errors;
if(data1 !== null){
const err2 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate57.errors = vErrors;
return false;
}
else {
errors = _errs4;
if(vErrors !== null){
if(_errs4){
vErrors.length = _errs4;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.files_completed !== undefined){
let data2 = data.files_completed;
const _errs9 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate57.errors = [{instancePath:instancePath+"/files_completed",schemaPath:"#/properties/files_completed/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs9){
if(typeof data2 == "number"){
if(data2 < 0 || isNaN(data2)){
validate57.errors = [{instancePath:instancePath+"/files_completed",schemaPath:"#/properties/files_completed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.phase !== undefined){
let data3 = data.phase;
const _errs11 = errors;
if(typeof data3 !== "string"){
validate57.errors = [{instancePath:instancePath+"/phase",schemaPath:"#/properties/phase/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data3 === "connecting") || (data3 === "downloading")) || (data3 === "retrying")) || (data3 === "verifying")) || (data3 === "completed")) || (data3 === "cancelled")) || (data3 === "failed"))){
validate57.errors = [{instancePath:instancePath+"/phase",schemaPath:"#/properties/phase/enum",keyword:"enum",params:{allowedValues: schema24.properties.phase.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speed_bps !== undefined){
let data4 = data.speed_bps;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data4 == "number"){
if(data4 < 0 || isNaN(data4)){
validate57.errors = [{instancePath:instancePath+"/speed_bps",schemaPath:"#/properties/speed_bps/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
else {
validate57.errors = [{instancePath:instancePath+"/speed_bps",schemaPath:"#/properties/speed_bps/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_bytes !== undefined){
let data5 = data.total_bytes;
const _errs15 = errors;
const _errs16 = errors;
let valid2 = false;
const _errs17 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
const err4 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
if(errors === _errs17){
if(typeof data5 == "number"){
if(data5 < 0 || isNaN(data5)){
const err5 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
}
}
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
const _errs19 = errors;
if(data5 !== null){
const err6 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs19 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate57.errors = vErrors;
return false;
}
else {
errors = _errs16;
if(vErrors !== null){
if(_errs16){
vErrors.length = _errs16;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_files !== undefined){
let data6 = data.total_files;
const _errs21 = errors;
if(!((typeof data6 == "number") && (!(data6 % 1) && !isNaN(data6)))){
validate57.errors = [{instancePath:instancePath+"/total_files",schemaPath:"#/properties/total_files/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs21){
if(typeof data6 == "number"){
if(data6 < 0 || isNaN(data6)){
validate57.errors = [{instancePath:instancePath+"/total_files",schemaPath:"#/properties/total_files/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate57.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate57.errors = vErrors;
return errors === 0;
}
validate57.evaluated = {"props":{"downloaded_bytes":true,"eta_seconds":true,"files_completed":true,"phase":true,"speed_bps":true,"total_bytes":true,"total_files":true},"dynamicProps":false,"dynamicItems":false};


function validate56(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate56.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.model_id === undefined) && (missing0 = "model_id")) || ((data.state === undefined) && (missing0 = "state"))) || ((data.download === undefined) && (missing0 = "download"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.runtime_available === undefined) && (missing0 = "runtime_available"))) || ((data.recommended === undefined) && (missing0 = "recommended"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.download !== undefined){
let data0 = data.download;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate57(data0, {instancePath:instancePath+"/download",parentData:data,parentDataProperty:"download",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.downloaded_bytes = true;
props0.eta_seconds = true;
props0.files_completed = true;
props0.phase = true;
props0.speed_bps = true;
props0.total_bytes = true;
props0.total_files = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data1 = data.error;
const _errs6 = errors;
const _errs7 = errors;
let valid2 = false;
const _errs8 = errors;
if(typeof data1 !== "string"){
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs8 === errors;
valid2 = valid2 || _valid1;
const _errs10 = errors;
if(data1 !== null){
const err3 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs7;
if(vErrors !== null){
if(_errs7){
vErrors.length = _errs7;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_id !== undefined){
const _errs12 = errors;
if(typeof data.model_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.recommended !== undefined){
const _errs14 = errors;
if(typeof data.recommended !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/recommended",schemaPath:"#/properties/recommended/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_available !== undefined){
const _errs16 = errors;
if(typeof data.runtime_available !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/runtime_available",schemaPath:"#/properties/runtime_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data5 = data.state;
const _errs18 = errors;
if(typeof data5 !== "string"){
validate56.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data5 === "missing") || (data5 === "downloading")) || (data5 === "ready")) || (data5 === "failed")) || (data5 === "cancelled"))){
validate56.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema23.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"download":true,"error":true,"model_id":true,"recommended":true,"runtime_available":true,"state":true},"dynamicProps":false,"dynamicItems":false};

const schema25 = {"properties":{"id":{"title":"Id","type":"string"},"language":{"title":"Language","type":"string"},"name":{"default":"","title":"Name","type":"string"}},"required":["id","language","name"],"title":"VoiceInfo","type":"object"};

function validate60(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate60.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.id === undefined) && (missing0 = "id")) || ((data.language === undefined) && (missing0 = "language"))) || ((data.name === undefined) && (missing0 = "name"))){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.id !== undefined){
const _errs1 = errors;
if(typeof data.id !== "string"){
validate60.errors = [{instancePath:instancePath+"/id",schemaPath:"#/properties/id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.language !== undefined){
const _errs3 = errors;
if(typeof data.language !== "string"){
validate60.errors = [{instancePath:instancePath+"/language",schemaPath:"#/properties/language/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs5 = errors;
if(typeof data.name !== "string"){
validate60.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate60.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate60.errors = vErrors;
return errors === 0;
}
validate60.evaluated = {"props":{"id":true,"language":true,"name":true},"dynamicProps":false,"dynamicItems":false};


function validate55(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate55.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((data.engine === undefined) && (missing0 = "engine")) || ((data.model_id === undefined) && (missing0 = "model_id"))) || ((data.name === undefined) && (missing0 = "name"))) || ((data.provider_id === undefined) && (missing0 = "provider_id"))) || ((data.provider_name === undefined) && (missing0 = "provider_name"))) || ((data.voices === undefined) && (missing0 = "voices"))) || ((data.custom_voice === undefined) && (missing0 = "custom_voice"))) || ((data.custom_model === undefined) && (missing0 = "custom_model"))) || ((data.speed_min === undefined) && (missing0 = "speed_min"))) || ((data.speed_max === undefined) && (missing0 = "speed_max"))) || ((data.instructions === undefined) && (missing0 = "instructions"))) || ((data.emotions === undefined) && (missing0 = "emotions"))) || ((data.download_bytes === undefined) && (missing0 = "download_bytes"))) || ((data.status === undefined) && (missing0 = "status"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.custom_model !== undefined){
const _errs1 = errors;
if(typeof data.custom_model !== "boolean"){
validate55.errors = [{instancePath:instancePath+"/custom_model",schemaPath:"#/properties/custom_model/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.custom_voice !== undefined){
const _errs3 = errors;
if(typeof data.custom_voice !== "boolean"){
validate55.errors = [{instancePath:instancePath+"/custom_voice",schemaPath:"#/properties/custom_voice/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.download_bytes !== undefined){
let data2 = data.download_bytes;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate55.errors = [{instancePath:instancePath+"/download_bytes",schemaPath:"#/properties/download_bytes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.emotions !== undefined){
let data3 = data.emotions;
const _errs7 = errors;
if(errors === _errs7){
if(Array.isArray(data3)){
var valid1 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
const _errs9 = errors;
if(typeof data3[i0] !== "string"){
validate55.errors = [{instancePath:instancePath+"/emotions/" + i0,schemaPath:"#/properties/emotions/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs9 === errors;
if(!valid1){
break;
}
}
}
else {
validate55.errors = [{instancePath:instancePath+"/emotions",schemaPath:"#/properties/emotions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.engine !== undefined){
let data5 = data.engine;
const _errs11 = errors;
if(typeof data5 !== "string"){
validate55.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data5 === "local") || (data5 === "remote"))){
validate55.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/enum",keyword:"enum",params:{allowedValues: schema22.properties.engine.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.instructions !== undefined){
const _errs13 = errors;
if(typeof data.instructions !== "boolean"){
validate55.errors = [{instancePath:instancePath+"/instructions",schemaPath:"#/properties/instructions/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_id !== undefined){
const _errs15 = errors;
if(typeof data.model_id !== "string"){
validate55.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs17 = errors;
if(typeof data.name !== "string"){
validate55.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_id !== undefined){
let data9 = data.provider_id;
const _errs19 = errors;
const _errs20 = errors;
let valid2 = false;
const _errs21 = errors;
if(typeof data9 !== "string"){
const err0 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs21 === errors;
valid2 = valid2 || _valid0;
const _errs23 = errors;
if(data9 !== null){
const err1 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs23 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err2 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_name !== undefined){
const _errs25 = errors;
if(typeof data.provider_name !== "string"){
validate55.errors = [{instancePath:instancePath+"/provider_name",schemaPath:"#/properties/provider_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speed_max !== undefined){
let data11 = data.speed_max;
const _errs27 = errors;
const _errs28 = errors;
let valid3 = false;
const _errs29 = errors;
if(!(typeof data11 == "number")){
const err3 = {instancePath:instancePath+"/speed_max",schemaPath:"#/properties/speed_max/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs29 === errors;
valid3 = valid3 || _valid1;
const _errs31 = errors;
if(data11 !== null){
const err4 = {instancePath:instancePath+"/speed_max",schemaPath:"#/properties/speed_max/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs31 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/speed_max",schemaPath:"#/properties/speed_max/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs28;
if(vErrors !== null){
if(_errs28){
vErrors.length = _errs28;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speed_min !== undefined){
let data12 = data.speed_min;
const _errs33 = errors;
const _errs34 = errors;
let valid4 = false;
const _errs35 = errors;
if(!(typeof data12 == "number")){
const err6 = {instancePath:instancePath+"/speed_min",schemaPath:"#/properties/speed_min/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs35 === errors;
valid4 = valid4 || _valid2;
const _errs37 = errors;
if(data12 !== null){
const err7 = {instancePath:instancePath+"/speed_min",schemaPath:"#/properties/speed_min/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs37 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/speed_min",schemaPath:"#/properties/speed_min/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs34;
if(vErrors !== null){
if(_errs34){
vErrors.length = _errs34;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data13 = data.status;
const _errs39 = errors;
const _errs40 = errors;
let valid5 = false;
const _errs41 = errors;
if(!(validate56(data13, {instancePath:instancePath+"/status",parentData:data,parentDataProperty:"status",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var _valid3 = _errs41 === errors;
valid5 = valid5 || _valid3;
if(_valid3){
var props0 = {};
props0.download = true;
props0.error = true;
props0.model_id = true;
props0.recommended = true;
props0.runtime_available = true;
props0.state = true;
}
const _errs42 = errors;
if(data13 !== null){
const err9 = {instancePath:instancePath+"/status",schemaPath:"#/properties/status/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs42 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err10 = {instancePath:instancePath+"/status",schemaPath:"#/properties/status/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs40;
if(vErrors !== null){
if(_errs40){
vErrors.length = _errs40;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.voices !== undefined){
let data14 = data.voices;
const _errs44 = errors;
if(errors === _errs44){
if(Array.isArray(data14)){
var valid6 = true;
const len1 = data14.length;
for(let i1=0; i1<len1; i1++){
const _errs46 = errors;
if(!(validate60(data14[i1], {instancePath:instancePath+"/voices/" + i1,parentData:data14,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var valid6 = _errs46 === errors;
if(!valid6){
break;
}
}
}
else {
validate55.errors = [{instancePath:instancePath+"/voices",schemaPath:"#/properties/voices/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate55.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate55.errors = vErrors;
return errors === 0;
}
validate55.evaluated = {"props":{"custom_model":true,"custom_voice":true,"download_bytes":true,"emotions":true,"engine":true,"instructions":true,"model_id":true,"name":true,"provider_id":true,"provider_name":true,"speed_max":true,"speed_min":true,"status":true,"voices":true},"dynamicProps":false,"dynamicItems":false};

const schema26 = {"additionalProperties":false,"properties":{"emotion":{"default":"","maxLength":30,"title":"Emotion","type":"string"},"engine":{"default":"local","enum":["local","remote"],"title":"Engine","type":"string"},"instructions":{"default":"","maxLength":2000,"title":"Instructions","type":"string"},"local_model":{"default":"kokoro-multi-lang-v1_0","enum":["kokoro-multi-lang-v1_0","vits-melo-tts-zh_en"],"title":"Local Model","type":"string"},"local_speed":{"default":1,"maximum":2,"minimum":0.5,"title":"Local Speed","type":"number"},"local_voice":{"default":"zf_xiaobei","title":"Local Voice","type":"string"},"provider_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Provider Id"},"remote_model":{"default":"","maxLength":200,"title":"Remote Model","type":"string"},"remote_speed":{"default":1,"maximum":4,"minimum":0.25,"title":"Remote Speed","type":"number"},"remote_voice":{"default":"","maxLength":200,"title":"Remote Voice","type":"string"}},"required":["engine","provider_id","local_model","local_voice","local_speed","remote_model","remote_voice","remote_speed","instructions","emotion"],"title":"TTSSettings","type":"object"};
const func1 = Object.prototype.hasOwnProperty;
const func2 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });

function validate63(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate63.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((data.engine === undefined) && (missing0 = "engine")) || ((data.provider_id === undefined) && (missing0 = "provider_id"))) || ((data.local_model === undefined) && (missing0 = "local_model"))) || ((data.local_voice === undefined) && (missing0 = "local_voice"))) || ((data.local_speed === undefined) && (missing0 = "local_speed"))) || ((data.remote_model === undefined) && (missing0 = "remote_model"))) || ((data.remote_voice === undefined) && (missing0 = "remote_voice"))) || ((data.remote_speed === undefined) && (missing0 = "remote_speed"))) || ((data.instructions === undefined) && (missing0 = "instructions"))) || ((data.emotion === undefined) && (missing0 = "emotion"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func1.call(schema26.properties, key0))){
validate63.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.emotion !== undefined){
let data0 = data.emotion;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func2(data0) > 30){
validate63.errors = [{instancePath:instancePath+"/emotion",schemaPath:"#/properties/emotion/maxLength",keyword:"maxLength",params:{limit: 30},message:"must NOT have more than 30 characters"}];
return false;
}
}
else {
validate63.errors = [{instancePath:instancePath+"/emotion",schemaPath:"#/properties/emotion/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.engine !== undefined){
let data1 = data.engine;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate63.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data1 === "local") || (data1 === "remote"))){
validate63.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/enum",keyword:"enum",params:{allowedValues: schema26.properties.engine.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.instructions !== undefined){
let data2 = data.instructions;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 === "string"){
if(func2(data2) > 2000){
validate63.errors = [{instancePath:instancePath+"/instructions",schemaPath:"#/properties/instructions/maxLength",keyword:"maxLength",params:{limit: 2000},message:"must NOT have more than 2000 characters"}];
return false;
}
}
else {
validate63.errors = [{instancePath:instancePath+"/instructions",schemaPath:"#/properties/instructions/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_model !== undefined){
let data3 = data.local_model;
const _errs8 = errors;
if(typeof data3 !== "string"){
validate63.errors = [{instancePath:instancePath+"/local_model",schemaPath:"#/properties/local_model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data3 === "kokoro-multi-lang-v1_0") || (data3 === "vits-melo-tts-zh_en"))){
validate63.errors = [{instancePath:instancePath+"/local_model",schemaPath:"#/properties/local_model/enum",keyword:"enum",params:{allowedValues: schema26.properties.local_model.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_speed !== undefined){
let data4 = data.local_speed;
const _errs10 = errors;
if(errors === _errs10){
if(typeof data4 == "number"){
if(data4 > 2 || isNaN(data4)){
validate63.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2},message:"must be <= 2"}];
return false;
}
else {
if(data4 < 0.5 || isNaN(data4)){
validate63.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0.5},message:"must be >= 0.5"}];
return false;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_voice !== undefined){
const _errs12 = errors;
if(typeof data.local_voice !== "string"){
validate63.errors = [{instancePath:instancePath+"/local_voice",schemaPath:"#/properties/local_voice/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_id !== undefined){
let data6 = data.provider_id;
const _errs14 = errors;
const _errs15 = errors;
let valid1 = false;
const _errs16 = errors;
if(typeof data6 !== "string"){
const err0 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs16 === errors;
valid1 = valid1 || _valid0;
const _errs18 = errors;
if(data6 !== null){
const err1 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs18 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs15;
if(vErrors !== null){
if(_errs15){
vErrors.length = _errs15;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.remote_model !== undefined){
let data7 = data.remote_model;
const _errs20 = errors;
if(errors === _errs20){
if(typeof data7 === "string"){
if(func2(data7) > 200){
validate63.errors = [{instancePath:instancePath+"/remote_model",schemaPath:"#/properties/remote_model/maxLength",keyword:"maxLength",params:{limit: 200},message:"must NOT have more than 200 characters"}];
return false;
}
}
else {
validate63.errors = [{instancePath:instancePath+"/remote_model",schemaPath:"#/properties/remote_model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.remote_speed !== undefined){
let data8 = data.remote_speed;
const _errs22 = errors;
if(errors === _errs22){
if(typeof data8 == "number"){
if(data8 > 4 || isNaN(data8)){
validate63.errors = [{instancePath:instancePath+"/remote_speed",schemaPath:"#/properties/remote_speed/maximum",keyword:"maximum",params:{comparison: "<=", limit: 4},message:"must be <= 4"}];
return false;
}
else {
if(data8 < 0.25 || isNaN(data8)){
validate63.errors = [{instancePath:instancePath+"/remote_speed",schemaPath:"#/properties/remote_speed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0.25},message:"must be >= 0.25"}];
return false;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/remote_speed",schemaPath:"#/properties/remote_speed/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.remote_voice !== undefined){
let data9 = data.remote_voice;
const _errs24 = errors;
if(errors === _errs24){
if(typeof data9 === "string"){
if(func2(data9) > 200){
validate63.errors = [{instancePath:instancePath+"/remote_voice",schemaPath:"#/properties/remote_voice/maxLength",keyword:"maxLength",params:{limit: 200},message:"must NOT have more than 200 characters"}];
return false;
}
}
else {
validate63.errors = [{instancePath:instancePath+"/remote_voice",schemaPath:"#/properties/remote_voice/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate54(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate54.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.settings === undefined) && (missing0 = "settings")) || ((data.revision === undefined) && (missing0 = "revision"))) || ((data.models === undefined) && (missing0 = "models"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.models !== undefined){
let data0 = data.models;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate55(data0[i0], {instancePath:instancePath+"/models/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/models",schemaPath:"#/properties/models/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
const _errs4 = errors;
if(typeof data.revision !== "string"){
validate54.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings !== undefined){
const _errs6 = errors;
if(!(validate63(data.settings, {instancePath:instancePath+"/settings",parentData:data,parentDataProperty:"settings",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate63.errors : vErrors.concat(validate63.errors);
errors = vErrors.length;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"models":true,"revision":true,"settings":true},"dynamicProps":false,"dynamicItems":false};

export const validateTTSModelStatus = validate65;

function validate65(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate65.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.model_id === undefined) && (missing0 = "model_id")) || ((data.state === undefined) && (missing0 = "state"))) || ((data.download === undefined) && (missing0 = "download"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.runtime_available === undefined) && (missing0 = "runtime_available"))) || ((data.recommended === undefined) && (missing0 = "recommended"))){
validate65.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.download !== undefined){
let data0 = data.download;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate57(data0, {instancePath:instancePath+"/download",parentData:data,parentDataProperty:"download",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.downloaded_bytes = true;
props0.eta_seconds = true;
props0.files_completed = true;
props0.phase = true;
props0.speed_bps = true;
props0.total_bytes = true;
props0.total_files = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate65.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data1 = data.error;
const _errs6 = errors;
const _errs7 = errors;
let valid2 = false;
const _errs8 = errors;
if(typeof data1 !== "string"){
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs8 === errors;
valid2 = valid2 || _valid1;
const _errs10 = errors;
if(data1 !== null){
const err3 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate65.errors = vErrors;
return false;
}
else {
errors = _errs7;
if(vErrors !== null){
if(_errs7){
vErrors.length = _errs7;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_id !== undefined){
const _errs12 = errors;
if(typeof data.model_id !== "string"){
validate65.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.recommended !== undefined){
const _errs14 = errors;
if(typeof data.recommended !== "boolean"){
validate65.errors = [{instancePath:instancePath+"/recommended",schemaPath:"#/properties/recommended/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_available !== undefined){
const _errs16 = errors;
if(typeof data.runtime_available !== "boolean"){
validate65.errors = [{instancePath:instancePath+"/runtime_available",schemaPath:"#/properties/runtime_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data5 = data.state;
const _errs18 = errors;
if(typeof data5 !== "string"){
validate65.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data5 === "missing") || (data5 === "downloading")) || (data5 === "ready")) || (data5 === "failed")) || (data5 === "cancelled"))){
validate65.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema23.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate65.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate65.errors = vErrors;
return errors === 0;
}
validate65.evaluated = {"props":{"download":true,"error":true,"model_id":true,"recommended":true,"runtime_available":true,"state":true},"dynamicProps":false,"dynamicItems":false};
