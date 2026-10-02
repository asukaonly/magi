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
const schema21 = {"properties":{"local_voices":{"items":{"$ref":"#/components/schemas/VoiceInfo"},"title":"Local Voices","type":"array"},"model":{"$ref":"#/components/schemas/TTSModelStatus"},"revision":{"title":"Revision","type":"string"},"settings":{"$ref":"#/components/schemas/TTSSettings"},"voices":{"items":{"$ref":"#/components/schemas/VoiceInfo"},"title":"Voices","type":"array"}},"required":["settings","revision","voices","local_voices","model"],"title":"TTSConfiguration","type":"object"};
const schema22 = {"properties":{"id":{"title":"Id","type":"string"},"language":{"title":"Language","type":"string"}},"required":["id","language"],"title":"VoiceInfo","type":"object"};

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
if(((data.id === undefined) && (missing0 = "id")) || ((data.language === undefined) && (missing0 = "language"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.id !== undefined){
const _errs1 = errors;
if(typeof data.id !== "string"){
validate55.errors = [{instancePath:instancePath+"/id",schemaPath:"#/properties/id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate55.errors = [{instancePath:instancePath+"/language",schemaPath:"#/properties/language/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
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
validate55.evaluated = {"props":{"id":true,"language":true},"dynamicProps":false,"dynamicItems":false};

const schema23 = {"properties":{"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"model_id":{"default":"kokoro-multi-lang-v1_0","title":"Model Id","type":"string"},"progress":{"default":0,"title":"Progress","type":"number"},"recommended":{"default":false,"title":"Recommended","type":"boolean"},"runtime_available":{"default":false,"title":"Runtime Available","type":"boolean"},"state":{"default":"missing","enum":["missing","downloading","ready","failed","cancelled"],"title":"State","type":"string"}},"required":["model_id","state","progress","error","runtime_available","recommended"],"title":"TTSModelStatus","type":"object"};

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
if(((((((data.model_id === undefined) && (missing0 = "model_id")) || ((data.state === undefined) && (missing0 = "state"))) || ((data.progress === undefined) && (missing0 = "progress"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.runtime_available === undefined) && (missing0 = "runtime_available"))) || ((data.recommended === undefined) && (missing0 = "recommended"))){
validate57.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.error !== undefined){
let data0 = data.error;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
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
validate57.errors = vErrors;
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
if(data.model_id !== undefined){
const _errs7 = errors;
if(typeof data.model_id !== "string"){
validate57.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress !== undefined){
const _errs9 = errors;
if(!(typeof data.progress == "number")){
validate57.errors = [{instancePath:instancePath+"/progress",schemaPath:"#/properties/progress/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.recommended !== undefined){
const _errs11 = errors;
if(typeof data.recommended !== "boolean"){
validate57.errors = [{instancePath:instancePath+"/recommended",schemaPath:"#/properties/recommended/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_available !== undefined){
const _errs13 = errors;
if(typeof data.runtime_available !== "boolean"){
validate57.errors = [{instancePath:instancePath+"/runtime_available",schemaPath:"#/properties/runtime_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data5 = data.state;
const _errs15 = errors;
if(typeof data5 !== "string"){
validate57.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data5 === "missing") || (data5 === "downloading")) || (data5 === "ready")) || (data5 === "failed")) || (data5 === "cancelled"))){
validate57.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema23.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs15 === errors;
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
validate57.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate57.errors = vErrors;
return errors === 0;
}
validate57.evaluated = {"props":{"error":true,"model_id":true,"progress":true,"recommended":true,"runtime_available":true,"state":true},"dynamicProps":false,"dynamicItems":false};

const schema24 = {"additionalProperties":false,"properties":{"engine":{"default":"local","enum":["local","remote"],"title":"Engine","type":"string"},"local_model":{"const":"kokoro-multi-lang-v1_0","default":"kokoro-multi-lang-v1_0","title":"Local Model","type":"string"},"local_speed":{"default":1,"maximum":2,"minimum":0.5,"title":"Local Speed","type":"number"},"local_voice":{"default":"zf_xiaobei","title":"Local Voice","type":"string"},"provider_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Provider Id"}},"required":["engine","provider_id","local_model","local_voice","local_speed"],"title":"TTSSettings","type":"object"};

function validate59(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate59.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.engine === undefined) && (missing0 = "engine")) || ((data.provider_id === undefined) && (missing0 = "provider_id"))) || ((data.local_model === undefined) && (missing0 = "local_model"))) || ((data.local_voice === undefined) && (missing0 = "local_voice"))) || ((data.local_speed === undefined) && (missing0 = "local_speed"))){
validate59.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "engine") || (key0 === "local_model")) || (key0 === "local_speed")) || (key0 === "local_voice")) || (key0 === "provider_id"))){
validate59.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.engine !== undefined){
let data0 = data.engine;
const _errs2 = errors;
if(typeof data0 !== "string"){
validate59.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data0 === "local") || (data0 === "remote"))){
validate59.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/enum",keyword:"enum",params:{allowedValues: schema24.properties.engine.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_model !== undefined){
let data1 = data.local_model;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate59.errors = [{instancePath:instancePath+"/local_model",schemaPath:"#/properties/local_model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("kokoro-multi-lang-v1_0" !== data1){
validate59.errors = [{instancePath:instancePath+"/local_model",schemaPath:"#/properties/local_model/const",keyword:"const",params:{allowedValue: "kokoro-multi-lang-v1_0"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_speed !== undefined){
let data2 = data.local_speed;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 == "number"){
if(data2 > 2 || isNaN(data2)){
validate59.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2},message:"must be <= 2"}];
return false;
}
else {
if(data2 < 0.5 || isNaN(data2)){
validate59.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0.5},message:"must be >= 0.5"}];
return false;
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/local_speed",schemaPath:"#/properties/local_speed/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.local_voice !== undefined){
const _errs8 = errors;
if(typeof data.local_voice !== "string"){
validate59.errors = [{instancePath:instancePath+"/local_voice",schemaPath:"#/properties/local_voice/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_id !== undefined){
let data4 = data.provider_id;
const _errs10 = errors;
const _errs11 = errors;
let valid1 = false;
const _errs12 = errors;
if(typeof data4 !== "string"){
const err0 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs12 === errors;
valid1 = valid1 || _valid0;
const _errs14 = errors;
if(data4 !== null){
const err1 = {instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs14 === errors;
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
validate59.errors = vErrors;
return false;
}
else {
errors = _errs11;
if(vErrors !== null){
if(_errs11){
vErrors.length = _errs11;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs10 === errors;
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
validate59.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate59.errors = vErrors;
return errors === 0;
}
validate59.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((((data.settings === undefined) && (missing0 = "settings")) || ((data.revision === undefined) && (missing0 = "revision"))) || ((data.voices === undefined) && (missing0 = "voices"))) || ((data.local_voices === undefined) && (missing0 = "local_voices"))) || ((data.model === undefined) && (missing0 = "model"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.local_voices !== undefined){
let data0 = data.local_voices;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate55(data0[i0], {instancePath:instancePath+"/local_voices/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
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
validate54.errors = [{instancePath:instancePath+"/local_voices",schemaPath:"#/properties/local_voices/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model !== undefined){
const _errs4 = errors;
if(!(validate57(data.model, {instancePath:instancePath+"/model",parentData:data,parentDataProperty:"model",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
const _errs5 = errors;
if(typeof data.revision !== "string"){
validate54.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings !== undefined){
const _errs7 = errors;
if(!(validate59(data.settings, {instancePath:instancePath+"/settings",parentData:data,parentDataProperty:"settings",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate59.errors : vErrors.concat(validate59.errors);
errors = vErrors.length;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.voices !== undefined){
let data5 = data.voices;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data5)){
var valid2 = true;
const len1 = data5.length;
for(let i1=0; i1<len1; i1++){
const _errs10 = errors;
if(!(validate55(data5[i1], {instancePath:instancePath+"/voices/" + i1,parentData:data5,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/voices",schemaPath:"#/properties/voices/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
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
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"local_voices":true,"model":true,"revision":true,"settings":true,"voices":true},"dynamicProps":false,"dynamicItems":false};

export const validateTTSModelStatus = validate62;

function validate62(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate62.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.model_id === undefined) && (missing0 = "model_id")) || ((data.state === undefined) && (missing0 = "state"))) || ((data.progress === undefined) && (missing0 = "progress"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.runtime_available === undefined) && (missing0 = "runtime_available"))) || ((data.recommended === undefined) && (missing0 = "recommended"))){
validate62.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.error !== undefined){
let data0 = data.error;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
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
validate62.errors = vErrors;
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
if(data.model_id !== undefined){
const _errs7 = errors;
if(typeof data.model_id !== "string"){
validate62.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress !== undefined){
const _errs9 = errors;
if(!(typeof data.progress == "number")){
validate62.errors = [{instancePath:instancePath+"/progress",schemaPath:"#/properties/progress/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.recommended !== undefined){
const _errs11 = errors;
if(typeof data.recommended !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/recommended",schemaPath:"#/properties/recommended/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_available !== undefined){
const _errs13 = errors;
if(typeof data.runtime_available !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/runtime_available",schemaPath:"#/properties/runtime_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data5 = data.state;
const _errs15 = errors;
if(typeof data5 !== "string"){
validate62.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data5 === "missing") || (data5 === "downloading")) || (data5 === "ready")) || (data5 === "failed")) || (data5 === "cancelled"))){
validate62.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema23.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs15 === errors;
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
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"props":{"error":true,"model_id":true,"progress":true,"recommended":true,"runtime_available":true,"state":true},"dynamicProps":false,"dynamicItems":false};
