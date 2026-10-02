// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateASRJob = validate53;
const schema20 = {"properties":{"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"expires_at":{"title":"Expires At","type":"number"},"request_id":{"title":"Request Id","type":"string"},"result":{"anyOf":[{"$ref":"#/components/schemas/TranscriptResult"},{"type":"null"}],"default":null},"runtime_id":{"title":"Runtime Id","type":"string"},"state":{"enum":["queued","running","succeeded","failed","cancelled"],"title":"State","type":"string"}},"required":["request_id","runtime_id","state","result","error","expires_at"],"title":"ASRJob","type":"object"};
const schema21 = {"properties":{"engine":{"enum":["local","remote"],"title":"Engine","type":"string"},"language":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Language"},"model":{"title":"Model","type":"string"},"no_speech":{"title":"No Speech","type":"boolean"},"text":{"maxLength":16000,"title":"Text","type":"string"}},"required":["text","language","no_speech","engine","model"],"title":"TranscriptResult","type":"object"};
const func1 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });

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
if((((((data.text === undefined) && (missing0 = "text")) || ((data.language === undefined) && (missing0 = "language"))) || ((data.no_speech === undefined) && (missing0 = "no_speech"))) || ((data.engine === undefined) && (missing0 = "engine"))) || ((data.model === undefined) && (missing0 = "model"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.engine !== undefined){
let data0 = data.engine;
const _errs1 = errors;
if(typeof data0 !== "string"){
validate54.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data0 === "local") || (data0 === "remote"))){
validate54.errors = [{instancePath:instancePath+"/engine",schemaPath:"#/properties/engine/enum",keyword:"enum",params:{allowedValues: schema21.properties.engine.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.language !== undefined){
let data1 = data.language;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/language",schemaPath:"#/properties/language/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs7 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/language",schemaPath:"#/properties/language/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/language",schemaPath:"#/properties/language/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate54.errors = vErrors;
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
if(data.model !== undefined){
const _errs9 = errors;
if(typeof data.model !== "string"){
validate54.errors = [{instancePath:instancePath+"/model",schemaPath:"#/properties/model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.no_speech !== undefined){
const _errs11 = errors;
if(typeof data.no_speech !== "boolean"){
validate54.errors = [{instancePath:instancePath+"/no_speech",schemaPath:"#/properties/no_speech/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.text !== undefined){
let data4 = data.text;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data4 === "string"){
if(func1(data4) > 16000){
validate54.errors = [{instancePath:instancePath+"/text",schemaPath:"#/properties/text/maxLength",keyword:"maxLength",params:{limit: 16000},message:"must NOT have more than 16000 characters"}];
return false;
}
}
else {
validate54.errors = [{instancePath:instancePath+"/text",schemaPath:"#/properties/text/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs13 === errors;
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
validate54.evaluated = {"props":{"engine":true,"language":true,"model":true,"no_speech":true,"text":true},"dynamicProps":false,"dynamicItems":false};


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
if(((((((data.request_id === undefined) && (missing0 = "request_id")) || ((data.runtime_id === undefined) && (missing0 = "runtime_id"))) || ((data.state === undefined) && (missing0 = "state"))) || ((data.result === undefined) && (missing0 = "result"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.expires_at === undefined) && (missing0 = "expires_at"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
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
validate53.errors = vErrors;
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
if(data.expires_at !== undefined){
const _errs7 = errors;
if(!(typeof data.expires_at == "number")){
validate53.errors = [{instancePath:instancePath+"/expires_at",schemaPath:"#/properties/expires_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.request_id !== undefined){
const _errs9 = errors;
if(typeof data.request_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.result !== undefined){
let data3 = data.result;
const _errs11 = errors;
const _errs12 = errors;
let valid2 = false;
const _errs13 = errors;
if(!(validate54(data3, {instancePath:instancePath+"/result",parentData:data,parentDataProperty:"result",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var _valid1 = _errs13 === errors;
valid2 = valid2 || _valid1;
if(_valid1){
var props0 = {};
props0.engine = true;
props0.language = true;
props0.model = true;
props0.no_speech = true;
props0.text = true;
}
const _errs14 = errors;
if(data3 !== null){
const err3 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs14 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs12;
if(vErrors !== null){
if(_errs12){
vErrors.length = _errs12;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_id !== undefined){
const _errs16 = errors;
if(typeof data.runtime_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/runtime_id",schemaPath:"#/properties/runtime_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate53.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data5 === "queued") || (data5 === "running")) || (data5 === "succeeded")) || (data5 === "failed")) || (data5 === "cancelled"))){
validate53.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema20.properties.state.enum},message:"must be equal to one of the allowed values"}];
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
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"error":true,"expires_at":true,"request_id":true,"result":true,"runtime_id":true,"state":true},"dynamicProps":false,"dynamicItems":false};

export const validateASRStatus = validate56;
const schema22 = {"properties":{"config_revision":{"title":"Config Revision","type":"string"},"enabled":{"title":"Enabled","type":"boolean"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"mode":{"enum":["local","remote"],"title":"Mode","type":"string"},"model":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Model"},"provider_name":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Provider Name"},"ready":{"title":"Ready","type":"boolean"},"runtime_id":{"title":"Runtime Id","type":"string"}},"required":["config_revision","runtime_id","enabled","mode","ready","error","provider_name","model"],"title":"ASRStatus","type":"object"};

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
if(((((((((data.config_revision === undefined) && (missing0 = "config_revision")) || ((data.runtime_id === undefined) && (missing0 = "runtime_id"))) || ((data.enabled === undefined) && (missing0 = "enabled"))) || ((data.mode === undefined) && (missing0 = "mode"))) || ((data.ready === undefined) && (missing0 = "ready"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.provider_name === undefined) && (missing0 = "provider_name"))) || ((data.model === undefined) && (missing0 = "model"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.config_revision !== undefined){
const _errs1 = errors;
if(typeof data.config_revision !== "string"){
validate56.errors = [{instancePath:instancePath+"/config_revision",schemaPath:"#/properties/config_revision/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs3 = errors;
if(typeof data.enabled !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data2 = data.error;
const _errs5 = errors;
const _errs6 = errors;
let valid1 = false;
const _errs7 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
const _errs9 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs9 === errors;
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
validate56.errors = vErrors;
return false;
}
else {
errors = _errs6;
if(vErrors !== null){
if(_errs6){
vErrors.length = _errs6;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.mode !== undefined){
let data3 = data.mode;
const _errs11 = errors;
if(typeof data3 !== "string"){
validate56.errors = [{instancePath:instancePath+"/mode",schemaPath:"#/properties/mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data3 === "local") || (data3 === "remote"))){
validate56.errors = [{instancePath:instancePath+"/mode",schemaPath:"#/properties/mode/enum",keyword:"enum",params:{allowedValues: schema22.properties.mode.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model !== undefined){
let data4 = data.model;
const _errs13 = errors;
const _errs14 = errors;
let valid2 = false;
const _errs15 = errors;
if(typeof data4 !== "string"){
const err3 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid2 = valid2 || _valid1;
const _errs17 = errors;
if(data4 !== null){
const err4 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_name !== undefined){
let data5 = data.provider_name;
const _errs19 = errors;
const _errs20 = errors;
let valid3 = false;
const _errs21 = errors;
if(typeof data5 !== "string"){
const err6 = {instancePath:instancePath+"/provider_name",schemaPath:"#/properties/provider_name/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
const _errs23 = errors;
if(data5 !== null){
const err7 = {instancePath:instancePath+"/provider_name",schemaPath:"#/properties/provider_name/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs23 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/provider_name",schemaPath:"#/properties/provider_name/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate56.errors = vErrors;
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
if(data.ready !== undefined){
const _errs25 = errors;
if(typeof data.ready !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/ready",schemaPath:"#/properties/ready/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.runtime_id !== undefined){
const _errs27 = errors;
if(typeof data.runtime_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/runtime_id",schemaPath:"#/properties/runtime_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs27 === errors;
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
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"config_revision":true,"enabled":true,"error":true,"mode":true,"model":true,"provider_name":true,"ready":true,"runtime_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateASRModel = validate57;
const schema23 = {"properties":{"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"id":{"title":"Id","type":"string"},"label":{"title":"Label","type":"string"},"license":{"title":"License","type":"string"},"license_url":{"title":"License Url","type":"string"},"progress":{"default":0,"title":"Progress","type":"number"},"recommended":{"default":false,"title":"Recommended","type":"boolean"},"size_bytes":{"title":"Size Bytes","type":"integer"},"source_url":{"title":"Source Url","type":"string"},"state":{"enum":["missing","downloading","ready","failed","cancelled"],"title":"State","type":"string"}},"required":["id","label","size_bytes","license","license_url","source_url","recommended","state","progress","error"],"title":"ASRModel","type":"object"};

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
if(((((((((((data.id === undefined) && (missing0 = "id")) || ((data.label === undefined) && (missing0 = "label"))) || ((data.size_bytes === undefined) && (missing0 = "size_bytes"))) || ((data.license === undefined) && (missing0 = "license"))) || ((data.license_url === undefined) && (missing0 = "license_url"))) || ((data.source_url === undefined) && (missing0 = "source_url"))) || ((data.recommended === undefined) && (missing0 = "recommended"))) || ((data.state === undefined) && (missing0 = "state"))) || ((data.progress === undefined) && (missing0 = "progress"))) || ((data.error === undefined) && (missing0 = "error"))){
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
if(data.id !== undefined){
const _errs7 = errors;
if(typeof data.id !== "string"){
validate57.errors = [{instancePath:instancePath+"/id",schemaPath:"#/properties/id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs9 = errors;
if(typeof data.label !== "string"){
validate57.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.license !== undefined){
const _errs11 = errors;
if(typeof data.license !== "string"){
validate57.errors = [{instancePath:instancePath+"/license",schemaPath:"#/properties/license/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.license_url !== undefined){
const _errs13 = errors;
if(typeof data.license_url !== "string"){
validate57.errors = [{instancePath:instancePath+"/license_url",schemaPath:"#/properties/license_url/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress !== undefined){
const _errs15 = errors;
if(!(typeof data.progress == "number")){
validate57.errors = [{instancePath:instancePath+"/progress",schemaPath:"#/properties/progress/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.recommended !== undefined){
const _errs17 = errors;
if(typeof data.recommended !== "boolean"){
validate57.errors = [{instancePath:instancePath+"/recommended",schemaPath:"#/properties/recommended/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.size_bytes !== undefined){
let data7 = data.size_bytes;
const _errs19 = errors;
if(!((typeof data7 == "number") && (!(data7 % 1) && !isNaN(data7)))){
validate57.errors = [{instancePath:instancePath+"/size_bytes",schemaPath:"#/properties/size_bytes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_url !== undefined){
const _errs21 = errors;
if(typeof data.source_url !== "string"){
validate57.errors = [{instancePath:instancePath+"/source_url",schemaPath:"#/properties/source_url/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data9 = data.state;
const _errs23 = errors;
if(typeof data9 !== "string"){
validate57.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data9 === "missing") || (data9 === "downloading")) || (data9 === "ready")) || (data9 === "failed")) || (data9 === "cancelled"))){
validate57.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema23.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs23 === errors;
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
else {
validate57.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate57.errors = vErrors;
return errors === 0;
}
validate57.evaluated = {"props":{"error":true,"id":true,"label":true,"license":true,"license_url":true,"progress":true,"recommended":true,"size_bytes":true,"source_url":true,"state":true},"dynamicProps":false,"dynamicItems":false};

export const validateASRModels = validate58;
const schema24 = {"properties":{"models":{"items":{"$ref":"#/components/schemas/ASRModel"},"title":"Models","type":"array"}},"required":["models"],"title":"ASRModels","type":"object"};

function validate58(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate58.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.models === undefined) && (missing0 = "models")){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
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
if(!(validate57(data0[i0], {instancePath:instancePath+"/models/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/models",schemaPath:"#/properties/models/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
}
}
}
else {
validate58.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate58.errors = vErrors;
return errors === 0;
}
validate58.evaluated = {"props":{"models":true},"dynamicProps":false,"dynamicItems":false};
