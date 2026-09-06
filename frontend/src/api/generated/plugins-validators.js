// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validatePluginConnectionResponse = validate53;
const schema20 = {"additionalProperties":false,"properties":{"connection_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Connection Id","type":"string"},"credential_refs":{"additionalProperties":{"type":"string"},"title":"Credential Refs","type":"object"},"display_name":{"maxLength":256,"minLength":1,"title":"Display Name","type":"string"},"enabled":{"default":false,"title":"Enabled","type":"boolean"},"plugin_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Plugin Id","type":"string"},"readiness":{"items":{"$ref":"#/components/schemas/CapabilityReadiness"},"title":"Readiness","type":"array"},"revision":{"default":0,"minimum":0,"title":"Revision","type":"integer"},"settings":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"title":"Settings","type":"object"}},"required":["connection_id","plugin_id","display_name","enabled","settings","credential_refs","revision","readiness"],"title":"PluginConnectionResponse","type":"object"};
const func1 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });
const pattern3 = new RegExp("^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$", "u");
const schema21 = {"additionalProperties":false,"description":"One authoritative capability state shared by UI and execution admission.","properties":{"capability_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Capability Id","type":"string"},"connection_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Connection Id","type":"string"},"message":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message"},"reason_code":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Reason Code"},"status":{"$ref":"#/components/schemas/ConnectionStatus"}},"required":["capability_id","connection_id","status","reason_code","message"],"title":"CapabilityReadiness","type":"object"};
const schema22 = {"enum":["disabled","setup_required","auth_required","ready","degraded","failed"],"title":"ConnectionStatus","type":"string"};

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
if(typeof data !== "string"){
validate55.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((data === "disabled") || (data === "setup_required")) || (data === "auth_required")) || (data === "ready")) || (data === "degraded")) || (data === "failed"))){
validate55.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema22.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate55.errors = vErrors;
return errors === 0;
}
validate55.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if((((((data.capability_id === undefined) && (missing0 = "capability_id")) || ((data.connection_id === undefined) && (missing0 = "connection_id"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.reason_code === undefined) && (missing0 = "reason_code"))) || ((data.message === undefined) && (missing0 = "message"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "capability_id") || (key0 === "connection_id")) || (key0 === "message")) || (key0 === "reason_code")) || (key0 === "status"))){
validate54.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.capability_id !== undefined){
let data0 = data.capability_id;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func1(data0) > 128){
validate54.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate54.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate54.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.connection_id !== undefined){
let data1 = data.connection_id;
const _errs4 = errors;
if(errors === _errs4){
if(typeof data1 === "string"){
if(func1(data1) > 128){
validate54.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data1) < 1){
validate54.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data1)){
validate54.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
let data2 = data.message;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/message",schemaPath:"#/properties/message/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/message",schemaPath:"#/properties/message/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/message",schemaPath:"#/properties/message/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.reason_code !== undefined){
let data3 = data.reason_code;
const _errs12 = errors;
const _errs13 = errors;
let valid2 = false;
const _errs14 = errors;
if(typeof data3 !== "string"){
const err3 = {instancePath:instancePath+"/reason_code",schemaPath:"#/properties/reason_code/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const _errs16 = errors;
if(data3 !== null){
const err4 = {instancePath:instancePath+"/reason_code",schemaPath:"#/properties/reason_code/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs16 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/reason_code",schemaPath:"#/properties/reason_code/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate54.errors = vErrors;
return false;
}
else {
errors = _errs13;
if(vErrors !== null){
if(_errs13){
vErrors.length = _errs13;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
const _errs18 = errors;
if(!(validate55(data.status, {instancePath:instancePath+"/status",parentData:data,parentDataProperty:"status",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
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
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema23 = {};

function validate58(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
validate58.errors = null;
return true;
}
validate58.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if(((((((((data.connection_id === undefined) && (missing0 = "connection_id")) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.enabled === undefined) && (missing0 = "enabled"))) || ((data.settings === undefined) && (missing0 = "settings"))) || ((data.credential_refs === undefined) && (missing0 = "credential_refs"))) || ((data.revision === undefined) && (missing0 = "revision"))) || ((data.readiness === undefined) && (missing0 = "readiness"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((((key0 === "connection_id") || (key0 === "credential_refs")) || (key0 === "display_name")) || (key0 === "enabled")) || (key0 === "plugin_id")) || (key0 === "readiness")) || (key0 === "revision")) || (key0 === "settings"))){
validate53.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.connection_id !== undefined){
let data0 = data.connection_id;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func1(data0) > 128){
validate53.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate53.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate53.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.credential_refs !== undefined){
let data1 = data.credential_refs;
const _errs4 = errors;
if(errors === _errs4){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
for(const key1 in data1){
const _errs7 = errors;
if(typeof data1[key1] !== "string"){
validate53.errors = [{instancePath:instancePath+"/credential_refs/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/credential_refs/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs7 === errors;
if(!valid1){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/credential_refs",schemaPath:"#/properties/credential_refs/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
let data3 = data.display_name;
const _errs9 = errors;
if(errors === _errs9){
if(typeof data3 === "string"){
if(func1(data3) > 256){
validate53.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/maxLength",keyword:"maxLength",params:{limit: 256},message:"must NOT have more than 256 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate53.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs11 = errors;
if(typeof data.enabled !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
let data5 = data.plugin_id;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data5 === "string"){
if(func1(data5) > 128){
validate53.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data5) < 1){
validate53.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data5)){
validate53.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.readiness !== undefined){
let data6 = data.readiness;
const _errs15 = errors;
if(errors === _errs15){
if(Array.isArray(data6)){
var valid2 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs17 = errors;
if(!(validate54(data6[i0], {instancePath:instancePath+"/readiness/" + i0,parentData:data6,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid2 = _errs17 === errors;
if(!valid2){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/readiness",schemaPath:"#/properties/readiness/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
let data8 = data.revision;
const _errs18 = errors;
if(!((typeof data8 == "number") && (!(data8 % 1) && !isNaN(data8)))){
validate53.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs18){
if(typeof data8 == "number"){
if(data8 < 0 || isNaN(data8)){
validate53.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings !== undefined){
let data9 = data.settings;
const _errs20 = errors;
if(errors === _errs20){
if(data9 && typeof data9 == "object" && !Array.isArray(data9)){
for(const key2 in data9){
const _errs23 = errors;
if(!(validate58(data9[key2], {instancePath:instancePath+"/settings/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data9,parentDataProperty:key2,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var valid3 = _errs23 === errors;
if(!valid3){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/settings",schemaPath:"#/properties/settings/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs20 === errors;
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
else {
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validatePluginConnectionsResponse = validate60;
const schema24 = {"properties":{"connections":{"items":{"$ref":"#/components/schemas/PluginConnectionResponse"},"title":"Connections","type":"array"},"total":{"title":"Total","type":"integer"}},"required":["connections","total"],"title":"PluginConnectionsResponse","type":"object"};

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
if(((data.connections === undefined) && (missing0 = "connections")) || ((data.total === undefined) && (missing0 = "total"))){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.connections !== undefined){
let data0 = data.connections;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate53(data0[i0], {instancePath:instancePath+"/connections/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/connections",schemaPath:"#/properties/connections/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total !== undefined){
let data2 = data.total;
const _errs4 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate60.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
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
validate60.evaluated = {"props":{"connections":true,"total":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginPackageResponse = validate62;
const schema25 = {"properties":{"contributions":{"items":{"$ref":"#/components/schemas/PluginContributionResponse"},"title":"Contributions","type":"array"},"current_settings":{"additionalProperties":true,"title":"Current Settings","type":"object"},"enabled":{"title":"Enabled","type":"boolean"},"healthy":{"title":"Healthy","type":"boolean"},"last_error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Last Error"},"loaded":{"title":"Loaded","type":"boolean"},"manifest":{"$ref":"#/components/schemas/PluginManifestResponse"},"package_sha256":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Package Sha256"},"trusted":{"title":"Trusted","type":"boolean"}},"required":["manifest","enabled","trusted","package_sha256","loaded","healthy","last_error","contributions","current_settings"],"title":"PluginPackageResponse","type":"object"};
const schema26 = {"properties":{"contribution_id":{"title":"Contribution Id","type":"string"},"contribution_type":{"title":"Contribution Type","type":"string"},"description":{"title":"Description","type":"string"},"display_name":{"title":"Display Name","type":"string"},"fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldResponse"},"title":"Fields","type":"array"},"metadata":{"additionalProperties":true,"title":"Metadata","type":"object"},"plugin_id":{"title":"Plugin Id","type":"string"},"surface":{"enum":["extensions","tools","timeline"],"title":"Surface","type":"string"}},"required":["plugin_id","contribution_id","contribution_type","display_name","description","surface","fields","metadata"],"title":"PluginContributionResponse","type":"object"};
const schema27 = {"additionalProperties":false,"description":"Host-rendered plugin field, including translated presentation metadata.","properties":{"default":{"default":null,"title":"Default"},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"description_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description Translated"},"key":{"title":"Key","type":"string"},"label":{"title":"Label","type":"string"},"label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label Translated"},"maximum":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Maximum"},"minimum":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Minimum"},"options":{"items":{"$ref":"#/components/schemas/ExtensionFieldOptionResponse"},"title":"Options","type":"array"},"order":{"default":0,"title":"Order","type":"integer"},"path_kind":{"anyOf":[{"enum":["file","directory"],"type":"string"},{"type":"null"}],"default":null,"title":"Path Kind"},"placeholder":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Placeholder"},"required":{"default":false,"title":"Required","type":"boolean"},"section":{"default":"general","title":"Section","type":"string"},"section_note_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Section Note Translated"},"section_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Section Translated"},"surface":{"default":"extensions","enum":["extensions","tools","timeline"],"title":"Surface","type":"string"},"type":{"default":"input","enum":["switch","select","input","number","secret","path","tags"],"title":"Type","type":"string"}},"required":["key","type","path_kind","label","description","default","required","options","section","surface","order","placeholder","depends_on_key","depends_on_values","minimum","maximum","label_translated","description_translated","section_translated","section_note_translated"],"title":"ExtensionFieldResponse","type":"object"};
const func11 = Object.prototype.hasOwnProperty;
const schema28 = {"additionalProperties":false,"properties":{"label":{"title":"Label","type":"string"},"label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label Translated"},"value":{"title":"Value","type":"string"}},"required":["label","value","label_translated"],"title":"ExtensionFieldOptionResponse","type":"object"};

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
if((((data.label === undefined) && (missing0 = "label")) || ((data.value === undefined) && (missing0 = "value"))) || ((data.label_translated === undefined) && (missing0 = "label_translated"))){
validate65.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "label") || (key0 === "label_translated")) || (key0 === "value"))){
validate65.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.label !== undefined){
const _errs2 = errors;
if(typeof data.label !== "string"){
validate65.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label_translated !== undefined){
let data1 = data.label_translated;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate65.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.value !== undefined){
const _errs10 = errors;
if(typeof data.value !== "string"){
validate65.errors = [{instancePath:instancePath+"/value",schemaPath:"#/properties/value/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
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
else {
validate65.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate65.errors = vErrors;
return errors === 0;
}
validate65.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate64(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate64.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((((((data.key === undefined) && (missing0 = "key")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.path_kind === undefined) && (missing0 = "path_kind"))) || ((data.label === undefined) && (missing0 = "label"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.default === undefined) && (missing0 = "default"))) || ((data.required === undefined) && (missing0 = "required"))) || ((data.options === undefined) && (missing0 = "options"))) || ((data.section === undefined) && (missing0 = "section"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.placeholder === undefined) && (missing0 = "placeholder"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))) || ((data.minimum === undefined) && (missing0 = "minimum"))) || ((data.maximum === undefined) && (missing0 = "maximum"))) || ((data.label_translated === undefined) && (missing0 = "label_translated"))) || ((data.description_translated === undefined) && (missing0 = "description_translated"))) || ((data.section_translated === undefined) && (missing0 = "section_translated"))) || ((data.section_note_translated === undefined) && (missing0 = "section_note_translated"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema27.properties, key0))){
validate64.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.depends_on_key !== undefined){
let data0 = data.depends_on_key;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const _errs6 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_values !== undefined){
let data1 = data.depends_on_values;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(typeof data1[i0] !== "string"){
validate64.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs12 = errors;
if(typeof data.description !== "string"){
validate64.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_translated !== undefined){
let data4 = data.description_translated;
const _errs14 = errors;
const _errs15 = errors;
let valid3 = false;
const _errs16 = errors;
if(typeof data4 !== "string"){
const err3 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs16 === errors;
valid3 = valid3 || _valid1;
const _errs18 = errors;
if(data4 !== null){
const err4 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs18 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate64.errors = vErrors;
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
if(data.key !== undefined){
const _errs20 = errors;
if(typeof data.key !== "string"){
validate64.errors = [{instancePath:instancePath+"/key",schemaPath:"#/properties/key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs22 = errors;
if(typeof data.label !== "string"){
validate64.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label_translated !== undefined){
let data7 = data.label_translated;
const _errs24 = errors;
const _errs25 = errors;
let valid4 = false;
const _errs26 = errors;
if(typeof data7 !== "string"){
const err6 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs26 === errors;
valid4 = valid4 || _valid2;
const _errs28 = errors;
if(data7 !== null){
const err7 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs28 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.maximum !== undefined){
let data8 = data.maximum;
const _errs30 = errors;
const _errs31 = errors;
let valid5 = false;
const _errs32 = errors;
if(!(typeof data8 == "number")){
const err9 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs32 === errors;
valid5 = valid5 || _valid3;
const _errs34 = errors;
if(data8 !== null){
const err10 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs34 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err11 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs31;
if(vErrors !== null){
if(_errs31){
vErrors.length = _errs31;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.minimum !== undefined){
let data9 = data.minimum;
const _errs36 = errors;
const _errs37 = errors;
let valid6 = false;
const _errs38 = errors;
if(!(typeof data9 == "number")){
const err12 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs38 === errors;
valid6 = valid6 || _valid4;
const _errs40 = errors;
if(data9 !== null){
const err13 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err14 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs37;
if(vErrors !== null){
if(_errs37){
vErrors.length = _errs37;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.options !== undefined){
let data10 = data.options;
const _errs42 = errors;
if(errors === _errs42){
if(Array.isArray(data10)){
var valid7 = true;
const len1 = data10.length;
for(let i1=0; i1<len1; i1++){
const _errs44 = errors;
if(!(validate65(data10[i1], {instancePath:instancePath+"/options/" + i1,parentData:data10,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate65.errors : vErrors.concat(validate65.errors);
errors = vErrors.length;
}
var valid7 = _errs44 === errors;
if(!valid7){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/options",schemaPath:"#/properties/options/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data12 = data.order;
const _errs45 = errors;
if(!((typeof data12 == "number") && (!(data12 % 1) && !isNaN(data12)))){
validate64.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path_kind !== undefined){
let data13 = data.path_kind;
const _errs47 = errors;
const _errs48 = errors;
let valid8 = false;
const _errs49 = errors;
if(typeof data13 !== "string"){
const err15 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
if(!((data13 === "file") || (data13 === "directory"))){
const err16 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/enum",keyword:"enum",params:{allowedValues: schema27.properties.path_kind.anyOf[0].enum},message:"must be equal to one of the allowed values"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs49 === errors;
valid8 = valid8 || _valid5;
const _errs51 = errors;
if(data13 !== null){
const err17 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs51 === errors;
valid8 = valid8 || _valid5;
if(!valid8){
const err18 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs48;
if(vErrors !== null){
if(_errs48){
vErrors.length = _errs48;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.placeholder !== undefined){
let data14 = data.placeholder;
const _errs53 = errors;
const _errs54 = errors;
let valid9 = false;
const _errs55 = errors;
if(typeof data14 !== "string"){
const err19 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
var _valid6 = _errs55 === errors;
valid9 = valid9 || _valid6;
const _errs57 = errors;
if(data14 !== null){
const err20 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid6 = _errs57 === errors;
valid9 = valid9 || _valid6;
if(!valid9){
const err21 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs54;
if(vErrors !== null){
if(_errs54){
vErrors.length = _errs54;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs53 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.required !== undefined){
const _errs59 = errors;
if(typeof data.required !== "boolean"){
validate64.errors = [{instancePath:instancePath+"/required",schemaPath:"#/properties/required/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs59 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section !== undefined){
const _errs61 = errors;
if(typeof data.section !== "string"){
validate64.errors = [{instancePath:instancePath+"/section",schemaPath:"#/properties/section/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs61 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section_note_translated !== undefined){
let data17 = data.section_note_translated;
const _errs63 = errors;
const _errs64 = errors;
let valid10 = false;
const _errs65 = errors;
if(typeof data17 !== "string"){
const err22 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
}
var _valid7 = _errs65 === errors;
valid10 = valid10 || _valid7;
const _errs67 = errors;
if(data17 !== null){
const err23 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
var _valid7 = _errs67 === errors;
valid10 = valid10 || _valid7;
if(!valid10){
const err24 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs64;
if(vErrors !== null){
if(_errs64){
vErrors.length = _errs64;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs63 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section_translated !== undefined){
let data18 = data.section_translated;
const _errs69 = errors;
const _errs70 = errors;
let valid11 = false;
const _errs71 = errors;
if(typeof data18 !== "string"){
const err25 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err25];
}
else {
vErrors.push(err25);
}
errors++;
}
var _valid8 = _errs71 === errors;
valid11 = valid11 || _valid8;
const _errs73 = errors;
if(data18 !== null){
const err26 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err26];
}
else {
vErrors.push(err26);
}
errors++;
}
var _valid8 = _errs73 === errors;
valid11 = valid11 || _valid8;
if(!valid11){
const err27 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err27];
}
else {
vErrors.push(err27);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs70;
if(vErrors !== null){
if(_errs70){
vErrors.length = _errs70;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs69 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data19 = data.surface;
const _errs75 = errors;
if(typeof data19 !== "string"){
validate64.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data19 === "extensions") || (data19 === "tools")) || (data19 === "timeline"))){
validate64.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema27.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs75 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data20 = data.type;
const _errs77 = errors;
if(typeof data20 !== "string"){
validate64.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data20 === "switch") || (data20 === "select")) || (data20 === "input")) || (data20 === "number")) || (data20 === "secret")) || (data20 === "path")) || (data20 === "tags"))){
validate64.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/enum",keyword:"enum",params:{allowedValues: schema27.properties.type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs77 === errors;
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
}
}
}
}
}
}
else {
validate64.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate64.errors = vErrors;
return errors === 0;
}
validate64.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if(((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.contribution_id === undefined) && (missing0 = "contribution_id"))) || ((data.contribution_type === undefined) && (missing0 = "contribution_type"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.fields === undefined) && (missing0 = "fields"))) || ((data.metadata === undefined) && (missing0 = "metadata"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.contribution_id !== undefined){
const _errs1 = errors;
if(typeof data.contribution_id !== "string"){
validate63.errors = [{instancePath:instancePath+"/contribution_id",schemaPath:"#/properties/contribution_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_type !== undefined){
const _errs3 = errors;
if(typeof data.contribution_type !== "string"){
validate63.errors = [{instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs5 = errors;
if(typeof data.description !== "string"){
validate63.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
const _errs7 = errors;
if(typeof data.display_name !== "string"){
validate63.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fields !== undefined){
let data4 = data.fields;
const _errs9 = errors;
if(errors === _errs9){
if(Array.isArray(data4)){
var valid1 = true;
const len0 = data4.length;
for(let i0=0; i0<len0; i0++){
const _errs11 = errors;
if(!(validate64(data4[i0], {instancePath:instancePath+"/fields/" + i0,parentData:data4,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var valid1 = _errs11 === errors;
if(!valid1){
break;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/fields",schemaPath:"#/properties/fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.metadata !== undefined){
let data6 = data.metadata;
const _errs12 = errors;
if(errors === _errs12){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
}
else {
validate63.errors = [{instancePath:instancePath+"/metadata",schemaPath:"#/properties/metadata/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs15 = errors;
if(typeof data.plugin_id !== "string"){
validate63.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data8 = data.surface;
const _errs17 = errors;
if(typeof data8 !== "string"){
validate63.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data8 === "extensions") || (data8 === "tools")) || (data8 === "timeline"))){
validate63.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema26.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs17 === errors;
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
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":{"contribution_id":true,"contribution_type":true,"description":true,"display_name":true,"fields":true,"metadata":true,"plugin_id":true,"surface":true},"dynamicProps":false,"dynamicItems":false};

const schema29 = {"properties":{"activation_flow":{"anyOf":[{"$ref":"#/components/schemas/ActivationFlowResponse"},{"type":"null"}],"default":null},"author":{"title":"Author","type":"string"},"capabilities":{"items":{"$ref":"#/components/schemas/PluginCapability"},"title":"Capabilities","type":"array"},"consented_capabilities":{"anyOf":[{"items":{"$ref":"#/components/schemas/PluginCapability"},"type":"array"},{"type":"null"}],"default":null,"title":"Consented Capabilities"},"contribution_types":{"items":{"type":"string"},"title":"Contribution Types","type":"array"},"description":{"title":"Description","type":"string"},"display_group":{"anyOf":[{"$ref":"#/components/schemas/PluginDisplayGroupSpec"},{"type":"null"}],"default":null},"execution_mode":{"enum":["restricted_process","trusted_process"],"title":"Execution Mode","type":"string"},"icon":{"default":"","title":"Icon","type":"string"},"manifest_path":{"title":"Manifest Path","type":"string"},"min_sdk_version":{"title":"Min Sdk Version","type":"string"},"name":{"title":"Name","type":"string"},"official":{"title":"Official","type":"boolean"},"plugin_dir":{"title":"Plugin Dir","type":"string"},"plugin_id":{"title":"Plugin Id","type":"string"},"protocol_version":{"const":2,"title":"Protocol Version","type":"integer"},"settings_actions":{"items":{"$ref":"#/components/schemas/PluginSettingsActionResponse"},"title":"Settings Actions","type":"array"},"settings_fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldResponse"},"title":"Settings Fields","type":"array"},"settings_resources":{"items":{"$ref":"#/components/schemas/PluginSettingsResourceSpec"},"title":"Settings Resources","type":"array"},"settings_ui_blocks":{"items":{"$ref":"#/components/schemas/PluginSettingsUiBlockResponse"},"title":"Settings Ui Blocks","type":"array"},"source":{"title":"Source","type":"string"},"version":{"title":"Version","type":"string"}},"required":["protocol_version","min_sdk_version","execution_mode","settings_fields","activation_flow","settings_actions","settings_resources","settings_ui_blocks","plugin_id","name","version","description","author","icon","display_group","official","contribution_types","source","plugin_dir","manifest_path","capabilities","consented_capabilities"],"title":"PluginManifestResponse","type":"object"};
const schema30 = {"additionalProperties":false,"properties":{"authorize_on_confirm":{"default":false,"title":"Authorize On Confirm","type":"boolean"},"cancel_label":{"default":"Cancel","title":"Cancel Label","type":"string"},"cancel_label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Cancel Label Translated"},"configured_key":{"title":"Configured Key","type":"string"},"confirm_label":{"default":"Confirm","title":"Confirm Label","type":"string"},"confirm_label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Confirm Label Translated"},"description":{"default":"","title":"Description","type":"string"},"description_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description Translated"},"enabled_key":{"title":"Enabled Key","type":"string"},"fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldResponse"},"title":"Fields","type":"array"},"first_context":{"anyOf":[{"$ref":"#/components/schemas/ActivationFirstContextSpec"},{"type":"null"}],"default":null},"title":{"title":"Title","type":"string"},"title_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Title Translated"}},"required":["title","description","confirm_label","cancel_label","authorize_on_confirm","enabled_key","configured_key","fields","first_context","title_translated","description_translated","confirm_label_translated","cancel_label_translated"],"title":"ActivationFlowResponse","type":"object"};
const schema31 = {"additionalProperties":false,"description":"First-run-only activation settings applied by the host onboarding UI.","properties":{"max_items_per_sync":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Items Per Sync"},"settings_overrides":{"additionalProperties":true,"title":"Settings Overrides","type":"object"}},"required":["max_items_per_sync","settings_overrides"],"title":"ActivationFirstContextSpec","type":"object"};

function validate72(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate72.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.max_items_per_sync === undefined) && (missing0 = "max_items_per_sync")) || ((data.settings_overrides === undefined) && (missing0 = "settings_overrides"))){
validate72.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((key0 === "max_items_per_sync") || (key0 === "settings_overrides"))){
validate72.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.max_items_per_sync !== undefined){
let data0 = data.max_items_per_sync;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
const err0 = {instancePath:instancePath+"/max_items_per_sync",schemaPath:"#/properties/max_items_per_sync/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs4){
if(typeof data0 == "number"){
if(data0 < 1 || isNaN(data0)){
const err1 = {instancePath:instancePath+"/max_items_per_sync",schemaPath:"#/properties/max_items_per_sync/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
const _errs6 = errors;
if(data0 !== null){
const err2 = {instancePath:instancePath+"/max_items_per_sync",schemaPath:"#/properties/max_items_per_sync/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/max_items_per_sync",schemaPath:"#/properties/max_items_per_sync/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate72.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_overrides !== undefined){
let data1 = data.settings_overrides;
const _errs8 = errors;
if(errors === _errs8){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
}
else {
validate72.errors = [{instancePath:instancePath+"/settings_overrides",schemaPath:"#/properties/settings_overrides/type",keyword:"type",params:{type: "object"},message:"must be object"}];
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
else {
validate72.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate72.errors = vErrors;
return errors === 0;
}
validate72.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate70(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate70.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((((data.title === undefined) && (missing0 = "title")) || ((data.description === undefined) && (missing0 = "description"))) || ((data.confirm_label === undefined) && (missing0 = "confirm_label"))) || ((data.cancel_label === undefined) && (missing0 = "cancel_label"))) || ((data.authorize_on_confirm === undefined) && (missing0 = "authorize_on_confirm"))) || ((data.enabled_key === undefined) && (missing0 = "enabled_key"))) || ((data.configured_key === undefined) && (missing0 = "configured_key"))) || ((data.fields === undefined) && (missing0 = "fields"))) || ((data.first_context === undefined) && (missing0 = "first_context"))) || ((data.title_translated === undefined) && (missing0 = "title_translated"))) || ((data.description_translated === undefined) && (missing0 = "description_translated"))) || ((data.confirm_label_translated === undefined) && (missing0 = "confirm_label_translated"))) || ((data.cancel_label_translated === undefined) && (missing0 = "cancel_label_translated"))){
validate70.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema30.properties, key0))){
validate70.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.authorize_on_confirm !== undefined){
const _errs2 = errors;
if(typeof data.authorize_on_confirm !== "boolean"){
validate70.errors = [{instancePath:instancePath+"/authorize_on_confirm",schemaPath:"#/properties/authorize_on_confirm/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cancel_label !== undefined){
const _errs4 = errors;
if(typeof data.cancel_label !== "string"){
validate70.errors = [{instancePath:instancePath+"/cancel_label",schemaPath:"#/properties/cancel_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cancel_label_translated !== undefined){
let data2 = data.cancel_label_translated;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/cancel_label_translated",schemaPath:"#/properties/cancel_label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/cancel_label_translated",schemaPath:"#/properties/cancel_label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/cancel_label_translated",schemaPath:"#/properties/cancel_label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate70.errors = vErrors;
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
if(data.configured_key !== undefined){
const _errs12 = errors;
if(typeof data.configured_key !== "string"){
validate70.errors = [{instancePath:instancePath+"/configured_key",schemaPath:"#/properties/configured_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.confirm_label !== undefined){
const _errs14 = errors;
if(typeof data.confirm_label !== "string"){
validate70.errors = [{instancePath:instancePath+"/confirm_label",schemaPath:"#/properties/confirm_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.confirm_label_translated !== undefined){
let data5 = data.confirm_label_translated;
const _errs16 = errors;
const _errs17 = errors;
let valid2 = false;
const _errs18 = errors;
if(typeof data5 !== "string"){
const err3 = {instancePath:instancePath+"/confirm_label_translated",schemaPath:"#/properties/confirm_label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs18 === errors;
valid2 = valid2 || _valid1;
const _errs20 = errors;
if(data5 !== null){
const err4 = {instancePath:instancePath+"/confirm_label_translated",schemaPath:"#/properties/confirm_label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs20 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/confirm_label_translated",schemaPath:"#/properties/confirm_label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate70.errors = vErrors;
return false;
}
else {
errors = _errs17;
if(vErrors !== null){
if(_errs17){
vErrors.length = _errs17;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs22 = errors;
if(typeof data.description !== "string"){
validate70.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_translated !== undefined){
let data7 = data.description_translated;
const _errs24 = errors;
const _errs25 = errors;
let valid3 = false;
const _errs26 = errors;
if(typeof data7 !== "string"){
const err6 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs26 === errors;
valid3 = valid3 || _valid2;
const _errs28 = errors;
if(data7 !== null){
const err7 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs28 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate70.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled_key !== undefined){
const _errs30 = errors;
if(typeof data.enabled_key !== "string"){
validate70.errors = [{instancePath:instancePath+"/enabled_key",schemaPath:"#/properties/enabled_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fields !== undefined){
let data9 = data.fields;
const _errs32 = errors;
if(errors === _errs32){
if(Array.isArray(data9)){
var valid4 = true;
const len0 = data9.length;
for(let i0=0; i0<len0; i0++){
const _errs34 = errors;
if(!(validate64(data9[i0], {instancePath:instancePath+"/fields/" + i0,parentData:data9,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var valid4 = _errs34 === errors;
if(!valid4){
break;
}
}
}
else {
validate70.errors = [{instancePath:instancePath+"/fields",schemaPath:"#/properties/fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.first_context !== undefined){
let data11 = data.first_context;
const _errs35 = errors;
const _errs36 = errors;
let valid5 = false;
const _errs37 = errors;
if(!(validate72(data11, {instancePath:instancePath+"/first_context",parentData:data,parentDataProperty:"first_context",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate72.errors : vErrors.concat(validate72.errors);
errors = vErrors.length;
}
var _valid3 = _errs37 === errors;
valid5 = valid5 || _valid3;
const _errs38 = errors;
if(data11 !== null){
const err9 = {instancePath:instancePath+"/first_context",schemaPath:"#/properties/first_context/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs38 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err10 = {instancePath:instancePath+"/first_context",schemaPath:"#/properties/first_context/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
validate70.errors = vErrors;
return false;
}
else {
errors = _errs36;
if(vErrors !== null){
if(_errs36){
vErrors.length = _errs36;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs40 = errors;
if(typeof data.title !== "string"){
validate70.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs40 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title_translated !== undefined){
let data13 = data.title_translated;
const _errs42 = errors;
const _errs43 = errors;
let valid6 = false;
const _errs44 = errors;
if(typeof data13 !== "string"){
const err11 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid4 = _errs44 === errors;
valid6 = valid6 || _valid4;
const _errs46 = errors;
if(data13 !== null){
const err12 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs46 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err13 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
validate70.errors = vErrors;
return false;
}
else {
errors = _errs43;
if(vErrors !== null){
if(_errs43){
vErrors.length = _errs43;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs42 === errors;
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
validate70.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate70.errors = vErrors;
return errors === 0;
}
validate70.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema32 = {"additionalProperties":false,"description":"A requested capability, never a grant of runtime authority.\n\nThe host authorizes access for a connection separately. Unknown operations\ncannot become executable merely by appearing in a package declaration.\nThe publication policy validates the supported set: screen_recording,\naccessibility, calendar, photos, contacts, system_media, filesystem_read,\nfilesystem_write, network, subprocess.","properties":{"capability":{"title":"Capability","type":"string"},"optional":{"default":false,"title":"Optional","type":"boolean"},"reason":{"default":"","title":"Reason","type":"string"},"reason_i18n":{"additionalProperties":{"type":"string"},"title":"Reason I18N","type":"object"},"scope":{"items":{"type":"string"},"title":"Scope","type":"array"}},"required":["capability","scope","optional","reason","reason_i18n"],"title":"PluginCapability","type":"object"};

function validate75(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate75.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.capability === undefined) && (missing0 = "capability")) || ((data.scope === undefined) && (missing0 = "scope"))) || ((data.optional === undefined) && (missing0 = "optional"))) || ((data.reason === undefined) && (missing0 = "reason"))) || ((data.reason_i18n === undefined) && (missing0 = "reason_i18n"))){
validate75.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "capability") || (key0 === "optional")) || (key0 === "reason")) || (key0 === "reason_i18n")) || (key0 === "scope"))){
validate75.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.capability !== undefined){
const _errs2 = errors;
if(typeof data.capability !== "string"){
validate75.errors = [{instancePath:instancePath+"/capability",schemaPath:"#/properties/capability/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.optional !== undefined){
const _errs4 = errors;
if(typeof data.optional !== "boolean"){
validate75.errors = [{instancePath:instancePath+"/optional",schemaPath:"#/properties/optional/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reason !== undefined){
const _errs6 = errors;
if(typeof data.reason !== "string"){
validate75.errors = [{instancePath:instancePath+"/reason",schemaPath:"#/properties/reason/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reason_i18n !== undefined){
let data3 = data.reason_i18n;
const _errs8 = errors;
if(errors === _errs8){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key1 in data3){
const _errs11 = errors;
if(typeof data3[key1] !== "string"){
validate75.errors = [{instancePath:instancePath+"/reason_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/reason_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs11 === errors;
if(!valid1){
break;
}
}
}
else {
validate75.errors = [{instancePath:instancePath+"/reason_i18n",schemaPath:"#/properties/reason_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.scope !== undefined){
let data5 = data.scope;
const _errs13 = errors;
if(errors === _errs13){
if(Array.isArray(data5)){
var valid2 = true;
const len0 = data5.length;
for(let i0=0; i0<len0; i0++){
const _errs15 = errors;
if(typeof data5[i0] !== "string"){
validate75.errors = [{instancePath:instancePath+"/scope/" + i0,schemaPath:"#/properties/scope/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs15 === errors;
if(!valid2){
break;
}
}
}
else {
validate75.errors = [{instancePath:instancePath+"/scope",schemaPath:"#/properties/scope/type",keyword:"type",params:{type: "array"},message:"must be array"}];
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
}
else {
validate75.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate75.errors = vErrors;
return errors === 0;
}
validate75.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema33 = {"additionalProperties":false,"description":"User-facing grouping metadata for marketplace and installed plugin UIs.","properties":{"description":{"default":"","title":"Description","type":"string"},"description_i18n":{"additionalProperties":{"type":"string"},"title":"Description I18N","type":"object"},"icon":{"default":"","title":"Icon","type":"string"},"id":{"title":"Id","type":"string"},"member_label":{"default":"","title":"Member Label","type":"string"},"member_label_i18n":{"additionalProperties":{"type":"string"},"title":"Member Label I18N","type":"object"},"member_order":{"default":100,"title":"Member Order","type":"integer"},"name":{"title":"Name","type":"string"},"name_i18n":{"additionalProperties":{"type":"string"},"title":"Name I18N","type":"object"},"order":{"default":100,"title":"Order","type":"integer"}},"required":["id","name","name_i18n","description","description_i18n","icon","order","member_label","member_label_i18n","member_order"],"title":"PluginDisplayGroupSpec","type":"object"};

function validate78(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate78.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((data.id === undefined) && (missing0 = "id")) || ((data.name === undefined) && (missing0 = "name"))) || ((data.name_i18n === undefined) && (missing0 = "name_i18n"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.description_i18n === undefined) && (missing0 = "description_i18n"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.member_label === undefined) && (missing0 = "member_label"))) || ((data.member_label_i18n === undefined) && (missing0 = "member_label_i18n"))) || ((data.member_order === undefined) && (missing0 = "member_order"))){
validate78.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema33.properties, key0))){
validate78.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.description !== undefined){
const _errs2 = errors;
if(typeof data.description !== "string"){
validate78.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_i18n !== undefined){
let data1 = data.description_i18n;
const _errs4 = errors;
if(errors === _errs4){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
for(const key1 in data1){
const _errs7 = errors;
if(typeof data1[key1] !== "string"){
validate78.errors = [{instancePath:instancePath+"/description_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/description_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs7 === errors;
if(!valid1){
break;
}
}
}
else {
validate78.errors = [{instancePath:instancePath+"/description_i18n",schemaPath:"#/properties/description_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
const _errs9 = errors;
if(typeof data.icon !== "string"){
validate78.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.id !== undefined){
const _errs11 = errors;
if(typeof data.id !== "string"){
validate78.errors = [{instancePath:instancePath+"/id",schemaPath:"#/properties/id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_label !== undefined){
const _errs13 = errors;
if(typeof data.member_label !== "string"){
validate78.errors = [{instancePath:instancePath+"/member_label",schemaPath:"#/properties/member_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_label_i18n !== undefined){
let data6 = data.member_label_i18n;
const _errs15 = errors;
if(errors === _errs15){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
for(const key2 in data6){
const _errs18 = errors;
if(typeof data6[key2] !== "string"){
validate78.errors = [{instancePath:instancePath+"/member_label_i18n/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/member_label_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs18 === errors;
if(!valid2){
break;
}
}
}
else {
validate78.errors = [{instancePath:instancePath+"/member_label_i18n",schemaPath:"#/properties/member_label_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_order !== undefined){
let data8 = data.member_order;
const _errs20 = errors;
if(!((typeof data8 == "number") && (!(data8 % 1) && !isNaN(data8)))){
validate78.errors = [{instancePath:instancePath+"/member_order",schemaPath:"#/properties/member_order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs22 = errors;
if(typeof data.name !== "string"){
validate78.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name_i18n !== undefined){
let data10 = data.name_i18n;
const _errs24 = errors;
if(errors === _errs24){
if(data10 && typeof data10 == "object" && !Array.isArray(data10)){
for(const key3 in data10){
const _errs27 = errors;
if(typeof data10[key3] !== "string"){
validate78.errors = [{instancePath:instancePath+"/name_i18n/" + key3.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/name_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs27 === errors;
if(!valid3){
break;
}
}
}
else {
validate78.errors = [{instancePath:instancePath+"/name_i18n",schemaPath:"#/properties/name_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data12 = data.order;
const _errs29 = errors;
if(!((typeof data12 == "number") && (!(data12 % 1) && !isNaN(data12)))){
validate78.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
else {
validate78.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate78.errors = vErrors;
return errors === 0;
}
validate78.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema34 = {"additionalProperties":false,"properties":{"action_id":{"title":"Action Id","type":"string"},"button_label":{"default":"Run","title":"Button Label","type":"string"},"button_label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Button Label Translated"},"contribution_id":{"default":"","title":"Contribution Id","type":"string"},"contribution_type":{"anyOf":[{"$ref":"#/components/schemas/ContributionType"},{"type":"null"}],"default":null},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"description_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description Translated"},"destructive":{"default":false,"title":"Destructive","type":"boolean"},"label":{"title":"Label","type":"string"},"label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label Translated"},"order":{"default":0,"title":"Order","type":"integer"},"persist_settings_on_success":{"default":false,"title":"Persist Settings On Success","type":"boolean"},"poll_interval_ms":{"default":2000,"maximum":60000,"minimum":100,"title":"Poll Interval Ms","type":"integer"},"presentation":{"default":"inline","enum":["inline","qr_code"],"title":"Presentation","type":"string"},"requires_enabled":{"default":true,"title":"Requires Enabled","type":"boolean"},"surface":{"default":"extensions","enum":["extensions","tools","timeline"],"title":"Surface","type":"string"},"timeout_ms":{"default":480000,"maximum":3600000,"minimum":1,"title":"Timeout Ms","type":"integer"}},"required":["action_id","label","description","button_label","presentation","surface","contribution_id","contribution_type","order","destructive","requires_enabled","poll_interval_ms","timeout_ms","persist_settings_on_success","depends_on_key","depends_on_values","label_translated","description_translated","button_label_translated"],"title":"PluginSettingsActionResponse","type":"object"};
const schema35 = {"description":"Supported plugin contribution categories.","enum":["operation","provider","tool","source","channel","skill","hook","history_importer"],"title":"ContributionType","type":"string"};

function validate81(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate81.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(typeof data !== "string"){
validate81.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((((data === "operation") || (data === "provider")) || (data === "tool")) || (data === "source")) || (data === "channel")) || (data === "skill")) || (data === "hook")) || (data === "history_importer"))){
validate81.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema35.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate81.errors = vErrors;
return errors === 0;
}
validate81.evaluated = {"dynamicProps":false,"dynamicItems":false};


function validate80(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate80.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((((((((((data.action_id === undefined) && (missing0 = "action_id")) || ((data.label === undefined) && (missing0 = "label"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.button_label === undefined) && (missing0 = "button_label"))) || ((data.presentation === undefined) && (missing0 = "presentation"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.contribution_id === undefined) && (missing0 = "contribution_id"))) || ((data.contribution_type === undefined) && (missing0 = "contribution_type"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.destructive === undefined) && (missing0 = "destructive"))) || ((data.requires_enabled === undefined) && (missing0 = "requires_enabled"))) || ((data.poll_interval_ms === undefined) && (missing0 = "poll_interval_ms"))) || ((data.timeout_ms === undefined) && (missing0 = "timeout_ms"))) || ((data.persist_settings_on_success === undefined) && (missing0 = "persist_settings_on_success"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))) || ((data.label_translated === undefined) && (missing0 = "label_translated"))) || ((data.description_translated === undefined) && (missing0 = "description_translated"))) || ((data.button_label_translated === undefined) && (missing0 = "button_label_translated"))){
validate80.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema34.properties, key0))){
validate80.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.action_id !== undefined){
const _errs2 = errors;
if(typeof data.action_id !== "string"){
validate80.errors = [{instancePath:instancePath+"/action_id",schemaPath:"#/properties/action_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.button_label !== undefined){
const _errs4 = errors;
if(typeof data.button_label !== "string"){
validate80.errors = [{instancePath:instancePath+"/button_label",schemaPath:"#/properties/button_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.button_label_translated !== undefined){
let data2 = data.button_label_translated;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/button_label_translated",schemaPath:"#/properties/button_label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/button_label_translated",schemaPath:"#/properties/button_label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/button_label_translated",schemaPath:"#/properties/button_label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate80.errors = vErrors;
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
if(data.contribution_id !== undefined){
const _errs12 = errors;
if(typeof data.contribution_id !== "string"){
validate80.errors = [{instancePath:instancePath+"/contribution_id",schemaPath:"#/properties/contribution_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_type !== undefined){
let data4 = data.contribution_type;
const _errs14 = errors;
const _errs15 = errors;
let valid2 = false;
const _errs16 = errors;
if(!(validate81(data4, {instancePath:instancePath+"/contribution_type",parentData:data,parentDataProperty:"contribution_type",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate81.errors : vErrors.concat(validate81.errors);
errors = vErrors.length;
}
var _valid1 = _errs16 === errors;
valid2 = valid2 || _valid1;
const _errs17 = errors;
if(data4 !== null){
const err3 = {instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate80.errors = vErrors;
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
if(data.depends_on_key !== undefined){
let data5 = data.depends_on_key;
const _errs19 = errors;
const _errs20 = errors;
let valid3 = false;
const _errs21 = errors;
if(typeof data5 !== "string"){
const err5 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
const _errs23 = errors;
if(data5 !== null){
const err6 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs23 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err7 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate80.errors = vErrors;
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
if(data.depends_on_values !== undefined){
let data6 = data.depends_on_values;
const _errs25 = errors;
if(errors === _errs25){
if(Array.isArray(data6)){
var valid4 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs27 = errors;
if(typeof data6[i0] !== "string"){
validate80.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid4 = _errs27 === errors;
if(!valid4){
break;
}
}
}
else {
validate80.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs29 = errors;
if(typeof data.description !== "string"){
validate80.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_translated !== undefined){
let data9 = data.description_translated;
const _errs31 = errors;
const _errs32 = errors;
let valid5 = false;
const _errs33 = errors;
if(typeof data9 !== "string"){
const err8 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var _valid3 = _errs33 === errors;
valid5 = valid5 || _valid3;
const _errs35 = errors;
if(data9 !== null){
const err9 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs35 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err10 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
validate80.errors = vErrors;
return false;
}
else {
errors = _errs32;
if(vErrors !== null){
if(_errs32){
vErrors.length = _errs32;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.destructive !== undefined){
const _errs37 = errors;
if(typeof data.destructive !== "boolean"){
validate80.errors = [{instancePath:instancePath+"/destructive",schemaPath:"#/properties/destructive/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs39 = errors;
if(typeof data.label !== "string"){
validate80.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label_translated !== undefined){
let data12 = data.label_translated;
const _errs41 = errors;
const _errs42 = errors;
let valid6 = false;
const _errs43 = errors;
if(typeof data12 !== "string"){
const err11 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid4 = _errs43 === errors;
valid6 = valid6 || _valid4;
const _errs45 = errors;
if(data12 !== null){
const err12 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs45 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err13 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
validate80.errors = vErrors;
return false;
}
else {
errors = _errs42;
if(vErrors !== null){
if(_errs42){
vErrors.length = _errs42;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data13 = data.order;
const _errs47 = errors;
if(!((typeof data13 == "number") && (!(data13 % 1) && !isNaN(data13)))){
validate80.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persist_settings_on_success !== undefined){
const _errs49 = errors;
if(typeof data.persist_settings_on_success !== "boolean"){
validate80.errors = [{instancePath:instancePath+"/persist_settings_on_success",schemaPath:"#/properties/persist_settings_on_success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.poll_interval_ms !== undefined){
let data15 = data.poll_interval_ms;
const _errs51 = errors;
if(!((typeof data15 == "number") && (!(data15 % 1) && !isNaN(data15)))){
validate80.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs51){
if(typeof data15 == "number"){
if(data15 > 60000 || isNaN(data15)){
validate80.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/maximum",keyword:"maximum",params:{comparison: "<=", limit: 60000},message:"must be <= 60000"}];
return false;
}
else {
if(data15 < 100 || isNaN(data15)){
validate80.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 100},message:"must be >= 100"}];
return false;
}
}
}
}
var valid0 = _errs51 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.presentation !== undefined){
let data16 = data.presentation;
const _errs53 = errors;
if(typeof data16 !== "string"){
validate80.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data16 === "inline") || (data16 === "qr_code"))){
validate80.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/enum",keyword:"enum",params:{allowedValues: schema34.properties.presentation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs53 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.requires_enabled !== undefined){
const _errs55 = errors;
if(typeof data.requires_enabled !== "boolean"){
validate80.errors = [{instancePath:instancePath+"/requires_enabled",schemaPath:"#/properties/requires_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs55 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data18 = data.surface;
const _errs57 = errors;
if(typeof data18 !== "string"){
validate80.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data18 === "extensions") || (data18 === "tools")) || (data18 === "timeline"))){
validate80.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema34.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs57 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timeout_ms !== undefined){
let data19 = data.timeout_ms;
const _errs59 = errors;
if(!((typeof data19 == "number") && (!(data19 % 1) && !isNaN(data19)))){
validate80.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs59){
if(typeof data19 == "number"){
if(data19 > 3600000 || isNaN(data19)){
validate80.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/maximum",keyword:"maximum",params:{comparison: "<=", limit: 3600000},message:"must be <= 3600000"}];
return false;
}
else {
if(data19 < 1 || isNaN(data19)){
validate80.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs59 === errors;
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
}
}
}
}
}
}
else {
validate80.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate80.errors = vErrors;
return errors === 0;
}
validate80.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema36 = {"additionalProperties":false,"description":"Read-only settings resource exposed by a plugin.","properties":{"description":{"default":"","title":"Description","type":"string"},"metadata":{"additionalProperties":true,"title":"Metadata","type":"object"},"requires_enabled":{"default":true,"title":"Requires Enabled","type":"boolean"},"resource_name":{"title":"Resource Name","type":"string"},"resource_type":{"default":"collection","enum":["collection","channel_status"],"title":"Resource Type","type":"string"}},"required":["resource_name","resource_type","requires_enabled","description","metadata"],"title":"PluginSettingsResourceSpec","type":"object"};

function validate85(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate85.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.resource_name === undefined) && (missing0 = "resource_name")) || ((data.resource_type === undefined) && (missing0 = "resource_type"))) || ((data.requires_enabled === undefined) && (missing0 = "requires_enabled"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.metadata === undefined) && (missing0 = "metadata"))){
validate85.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "description") || (key0 === "metadata")) || (key0 === "requires_enabled")) || (key0 === "resource_name")) || (key0 === "resource_type"))){
validate85.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.description !== undefined){
const _errs2 = errors;
if(typeof data.description !== "string"){
validate85.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.metadata !== undefined){
let data1 = data.metadata;
const _errs4 = errors;
if(errors === _errs4){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
}
else {
validate85.errors = [{instancePath:instancePath+"/metadata",schemaPath:"#/properties/metadata/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.requires_enabled !== undefined){
const _errs7 = errors;
if(typeof data.requires_enabled !== "boolean"){
validate85.errors = [{instancePath:instancePath+"/requires_enabled",schemaPath:"#/properties/requires_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_name !== undefined){
const _errs9 = errors;
if(typeof data.resource_name !== "string"){
validate85.errors = [{instancePath:instancePath+"/resource_name",schemaPath:"#/properties/resource_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_type !== undefined){
let data4 = data.resource_type;
const _errs11 = errors;
if(typeof data4 !== "string"){
validate85.errors = [{instancePath:instancePath+"/resource_type",schemaPath:"#/properties/resource_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data4 === "collection") || (data4 === "channel_status"))){
validate85.errors = [{instancePath:instancePath+"/resource_type",schemaPath:"#/properties/resource_type/enum",keyword:"enum",params:{allowedValues: schema36.properties.resource_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs11 === errors;
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
validate85.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate85.errors = vErrors;
return errors === 0;
}
validate85.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema37 = {"additionalProperties":false,"properties":{"block_id":{"title":"Block Id","type":"string"},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"description_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description Translated"},"presentation":{"default":"list","enum":["calendar_list","list","permission_status"],"title":"Presentation","type":"string"},"resource_name":{"title":"Resource Name","type":"string"},"title":{"title":"Title","type":"string"},"title_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Title Translated"},"type":{"const":"resource_picker","default":"resource_picker","title":"Type","type":"string"},"value_key":{"title":"Value Key","type":"string"}},"required":["block_id","type","title","description","resource_name","value_key","presentation","depends_on_key","depends_on_values","title_translated","description_translated"],"title":"PluginSettingsUiBlockResponse","type":"object"};

function validate87(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate87.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((data.block_id === undefined) && (missing0 = "block_id")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.title === undefined) && (missing0 = "title"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.resource_name === undefined) && (missing0 = "resource_name"))) || ((data.value_key === undefined) && (missing0 = "value_key"))) || ((data.presentation === undefined) && (missing0 = "presentation"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))) || ((data.title_translated === undefined) && (missing0 = "title_translated"))) || ((data.description_translated === undefined) && (missing0 = "description_translated"))){
validate87.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema37.properties, key0))){
validate87.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.block_id !== undefined){
const _errs2 = errors;
if(typeof data.block_id !== "string"){
validate87.errors = [{instancePath:instancePath+"/block_id",schemaPath:"#/properties/block_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_key !== undefined){
let data1 = data.depends_on_key;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate87.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_values !== undefined){
let data2 = data.depends_on_values;
const _errs10 = errors;
if(errors === _errs10){
if(Array.isArray(data2)){
var valid2 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs12 = errors;
if(typeof data2[i0] !== "string"){
validate87.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs12 === errors;
if(!valid2){
break;
}
}
}
else {
validate87.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs14 = errors;
if(typeof data.description !== "string"){
validate87.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_translated !== undefined){
let data5 = data.description_translated;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(typeof data5 !== "string"){
const err3 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs18 === errors;
valid3 = valid3 || _valid1;
const _errs20 = errors;
if(data5 !== null){
const err4 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs20 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate87.errors = vErrors;
return false;
}
else {
errors = _errs17;
if(vErrors !== null){
if(_errs17){
vErrors.length = _errs17;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.presentation !== undefined){
let data6 = data.presentation;
const _errs22 = errors;
if(typeof data6 !== "string"){
validate87.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data6 === "calendar_list") || (data6 === "list")) || (data6 === "permission_status"))){
validate87.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/enum",keyword:"enum",params:{allowedValues: schema37.properties.presentation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_name !== undefined){
const _errs24 = errors;
if(typeof data.resource_name !== "string"){
validate87.errors = [{instancePath:instancePath+"/resource_name",schemaPath:"#/properties/resource_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs26 = errors;
if(typeof data.title !== "string"){
validate87.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title_translated !== undefined){
let data9 = data.title_translated;
const _errs28 = errors;
const _errs29 = errors;
let valid4 = false;
const _errs30 = errors;
if(typeof data9 !== "string"){
const err6 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs30 === errors;
valid4 = valid4 || _valid2;
const _errs32 = errors;
if(data9 !== null){
const err7 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs32 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/title_translated",schemaPath:"#/properties/title_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate87.errors = vErrors;
return false;
}
else {
errors = _errs29;
if(vErrors !== null){
if(_errs29){
vErrors.length = _errs29;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs28 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data10 = data.type;
const _errs34 = errors;
if(typeof data10 !== "string"){
validate87.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("resource_picker" !== data10){
validate87.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/const",keyword:"const",params:{allowedValue: "resource_picker"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.value_key !== undefined){
const _errs36 = errors;
if(typeof data.value_key !== "string"){
validate87.errors = [{instancePath:instancePath+"/value_key",schemaPath:"#/properties/value_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs36 === errors;
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
else {
validate87.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate87.errors = vErrors;
return errors === 0;
}
validate87.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate69(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate69.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((((((((data.protocol_version === undefined) && (missing0 = "protocol_version")) || ((data.min_sdk_version === undefined) && (missing0 = "min_sdk_version"))) || ((data.execution_mode === undefined) && (missing0 = "execution_mode"))) || ((data.settings_fields === undefined) && (missing0 = "settings_fields"))) || ((data.activation_flow === undefined) && (missing0 = "activation_flow"))) || ((data.settings_actions === undefined) && (missing0 = "settings_actions"))) || ((data.settings_resources === undefined) && (missing0 = "settings_resources"))) || ((data.settings_ui_blocks === undefined) && (missing0 = "settings_ui_blocks"))) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.name === undefined) && (missing0 = "name"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.author === undefined) && (missing0 = "author"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.display_group === undefined) && (missing0 = "display_group"))) || ((data.official === undefined) && (missing0 = "official"))) || ((data.contribution_types === undefined) && (missing0 = "contribution_types"))) || ((data.source === undefined) && (missing0 = "source"))) || ((data.plugin_dir === undefined) && (missing0 = "plugin_dir"))) || ((data.manifest_path === undefined) && (missing0 = "manifest_path"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))) || ((data.consented_capabilities === undefined) && (missing0 = "consented_capabilities"))){
validate69.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.activation_flow !== undefined){
let data0 = data.activation_flow;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate70(data0, {instancePath:instancePath+"/activation_flow",parentData:data,parentDataProperty:"activation_flow",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate70.errors : vErrors.concat(validate70.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/activation_flow",schemaPath:"#/properties/activation_flow/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err1 = {instancePath:instancePath+"/activation_flow",schemaPath:"#/properties/activation_flow/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate69.errors = vErrors;
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
if(data.author !== undefined){
const _errs6 = errors;
if(typeof data.author !== "string"){
validate69.errors = [{instancePath:instancePath+"/author",schemaPath:"#/properties/author/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.capabilities !== undefined){
let data2 = data.capabilities;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data2)){
var valid2 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(!(validate75(data2[i0], {instancePath:instancePath+"/capabilities/" + i0,parentData:data2,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate75.errors : vErrors.concat(validate75.errors);
errors = vErrors.length;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/capabilities",schemaPath:"#/properties/capabilities/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.consented_capabilities !== undefined){
let data4 = data.consented_capabilities;
const _errs11 = errors;
const _errs12 = errors;
let valid3 = false;
const _errs13 = errors;
if(errors === _errs13){
if(Array.isArray(data4)){
var valid4 = true;
const len1 = data4.length;
for(let i1=0; i1<len1; i1++){
const _errs15 = errors;
if(!(validate75(data4[i1], {instancePath:instancePath+"/consented_capabilities/" + i1,parentData:data4,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate75.errors : vErrors.concat(validate75.errors);
errors = vErrors.length;
}
var valid4 = _errs15 === errors;
if(!valid4){
break;
}
}
}
else {
const err2 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
}
var _valid1 = _errs13 === errors;
valid3 = valid3 || _valid1;
const _errs16 = errors;
if(data4 !== null){
const err3 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs16 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err4 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate69.errors = vErrors;
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
if(data.contribution_types !== undefined){
let data6 = data.contribution_types;
const _errs18 = errors;
if(errors === _errs18){
if(Array.isArray(data6)){
var valid5 = true;
const len2 = data6.length;
for(let i2=0; i2<len2; i2++){
const _errs20 = errors;
if(typeof data6[i2] !== "string"){
validate69.errors = [{instancePath:instancePath+"/contribution_types/" + i2,schemaPath:"#/properties/contribution_types/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid5 = _errs20 === errors;
if(!valid5){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/contribution_types",schemaPath:"#/properties/contribution_types/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs22 = errors;
if(typeof data.description !== "string"){
validate69.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_group !== undefined){
let data9 = data.display_group;
const _errs24 = errors;
const _errs25 = errors;
let valid6 = false;
const _errs26 = errors;
if(!(validate78(data9, {instancePath:instancePath+"/display_group",parentData:data,parentDataProperty:"display_group",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate78.errors : vErrors.concat(validate78.errors);
errors = vErrors.length;
}
var _valid2 = _errs26 === errors;
valid6 = valid6 || _valid2;
const _errs27 = errors;
if(data9 !== null){
const err5 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid2 = _errs27 === errors;
valid6 = valid6 || _valid2;
if(!valid6){
const err6 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
validate69.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.execution_mode !== undefined){
let data10 = data.execution_mode;
const _errs29 = errors;
if(typeof data10 !== "string"){
validate69.errors = [{instancePath:instancePath+"/execution_mode",schemaPath:"#/properties/execution_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data10 === "restricted_process") || (data10 === "trusted_process"))){
validate69.errors = [{instancePath:instancePath+"/execution_mode",schemaPath:"#/properties/execution_mode/enum",keyword:"enum",params:{allowedValues: schema29.properties.execution_mode.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
const _errs31 = errors;
if(typeof data.icon !== "string"){
validate69.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest_path !== undefined){
const _errs33 = errors;
if(typeof data.manifest_path !== "string"){
validate69.errors = [{instancePath:instancePath+"/manifest_path",schemaPath:"#/properties/manifest_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.min_sdk_version !== undefined){
const _errs35 = errors;
if(typeof data.min_sdk_version !== "string"){
validate69.errors = [{instancePath:instancePath+"/min_sdk_version",schemaPath:"#/properties/min_sdk_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs37 = errors;
if(typeof data.name !== "string"){
validate69.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.official !== undefined){
const _errs39 = errors;
if(typeof data.official !== "boolean"){
validate69.errors = [{instancePath:instancePath+"/official",schemaPath:"#/properties/official/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_dir !== undefined){
const _errs41 = errors;
if(typeof data.plugin_dir !== "string"){
validate69.errors = [{instancePath:instancePath+"/plugin_dir",schemaPath:"#/properties/plugin_dir/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs43 = errors;
if(typeof data.plugin_id !== "string"){
validate69.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol_version !== undefined){
let data18 = data.protocol_version;
const _errs45 = errors;
if(!((typeof data18 == "number") && (!(data18 % 1) && !isNaN(data18)))){
validate69.errors = [{instancePath:instancePath+"/protocol_version",schemaPath:"#/properties/protocol_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(2 !== data18){
validate69.errors = [{instancePath:instancePath+"/protocol_version",schemaPath:"#/properties/protocol_version/const",keyword:"const",params:{allowedValue: 2},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_actions !== undefined){
let data19 = data.settings_actions;
const _errs47 = errors;
if(errors === _errs47){
if(Array.isArray(data19)){
var valid7 = true;
const len3 = data19.length;
for(let i3=0; i3<len3; i3++){
const _errs49 = errors;
if(!(validate80(data19[i3], {instancePath:instancePath+"/settings_actions/" + i3,parentData:data19,parentDataProperty:i3,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate80.errors : vErrors.concat(validate80.errors);
errors = vErrors.length;
}
var valid7 = _errs49 === errors;
if(!valid7){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/settings_actions",schemaPath:"#/properties/settings_actions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_fields !== undefined){
let data21 = data.settings_fields;
const _errs50 = errors;
if(errors === _errs50){
if(Array.isArray(data21)){
var valid8 = true;
const len4 = data21.length;
for(let i4=0; i4<len4; i4++){
const _errs52 = errors;
if(!(validate64(data21[i4], {instancePath:instancePath+"/settings_fields/" + i4,parentData:data21,parentDataProperty:i4,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var valid8 = _errs52 === errors;
if(!valid8){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/settings_fields",schemaPath:"#/properties/settings_fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs50 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_resources !== undefined){
let data23 = data.settings_resources;
const _errs53 = errors;
if(errors === _errs53){
if(Array.isArray(data23)){
var valid9 = true;
const len5 = data23.length;
for(let i5=0; i5<len5; i5++){
const _errs55 = errors;
if(!(validate85(data23[i5], {instancePath:instancePath+"/settings_resources/" + i5,parentData:data23,parentDataProperty:i5,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate85.errors : vErrors.concat(validate85.errors);
errors = vErrors.length;
}
var valid9 = _errs55 === errors;
if(!valid9){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/settings_resources",schemaPath:"#/properties/settings_resources/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs53 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_ui_blocks !== undefined){
let data25 = data.settings_ui_blocks;
const _errs56 = errors;
if(errors === _errs56){
if(Array.isArray(data25)){
var valid10 = true;
const len6 = data25.length;
for(let i6=0; i6<len6; i6++){
const _errs58 = errors;
if(!(validate87(data25[i6], {instancePath:instancePath+"/settings_ui_blocks/" + i6,parentData:data25,parentDataProperty:i6,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate87.errors : vErrors.concat(validate87.errors);
errors = vErrors.length;
}
var valid10 = _errs58 === errors;
if(!valid10){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/settings_ui_blocks",schemaPath:"#/properties/settings_ui_blocks/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs56 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source !== undefined){
const _errs59 = errors;
if(typeof data.source !== "string"){
validate69.errors = [{instancePath:instancePath+"/source",schemaPath:"#/properties/source/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs59 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
const _errs61 = errors;
if(typeof data.version !== "string"){
validate69.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs61 === errors;
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
}
}
}
}
}
}
}
}
else {
validate69.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate69.errors = vErrors;
return errors === 0;
}
validate69.evaluated = {"props":{"activation_flow":true,"author":true,"capabilities":true,"consented_capabilities":true,"contribution_types":true,"description":true,"display_group":true,"execution_mode":true,"icon":true,"manifest_path":true,"min_sdk_version":true,"name":true,"official":true,"plugin_dir":true,"plugin_id":true,"protocol_version":true,"settings_actions":true,"settings_fields":true,"settings_resources":true,"settings_ui_blocks":true,"source":true,"version":true},"dynamicProps":false,"dynamicItems":false};


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
if((((((((((data.manifest === undefined) && (missing0 = "manifest")) || ((data.enabled === undefined) && (missing0 = "enabled"))) || ((data.trusted === undefined) && (missing0 = "trusted"))) || ((data.package_sha256 === undefined) && (missing0 = "package_sha256"))) || ((data.loaded === undefined) && (missing0 = "loaded"))) || ((data.healthy === undefined) && (missing0 = "healthy"))) || ((data.last_error === undefined) && (missing0 = "last_error"))) || ((data.contributions === undefined) && (missing0 = "contributions"))) || ((data.current_settings === undefined) && (missing0 = "current_settings"))){
validate62.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.contributions !== undefined){
let data0 = data.contributions;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate63(data0[i0], {instancePath:instancePath+"/contributions/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate63.errors : vErrors.concat(validate63.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate62.errors = [{instancePath:instancePath+"/contributions",schemaPath:"#/properties/contributions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.current_settings !== undefined){
let data2 = data.current_settings;
const _errs4 = errors;
if(errors === _errs4){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
validate62.errors = [{instancePath:instancePath+"/current_settings",schemaPath:"#/properties/current_settings/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs7 = errors;
if(typeof data.enabled !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.healthy !== undefined){
const _errs9 = errors;
if(typeof data.healthy !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/healthy",schemaPath:"#/properties/healthy/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_error !== undefined){
let data5 = data.last_error;
const _errs11 = errors;
const _errs12 = errors;
let valid2 = false;
const _errs13 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs13 === errors;
valid2 = valid2 || _valid0;
const _errs15 = errors;
if(data5 !== null){
const err1 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs15 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err2 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.loaded !== undefined){
const _errs17 = errors;
if(typeof data.loaded !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/loaded",schemaPath:"#/properties/loaded/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest !== undefined){
const _errs19 = errors;
if(!(validate69(data.manifest, {instancePath:instancePath+"/manifest",parentData:data,parentDataProperty:"manifest",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate69.errors : vErrors.concat(validate69.errors);
errors = vErrors.length;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.package_sha256 !== undefined){
let data8 = data.package_sha256;
const _errs20 = errors;
const _errs21 = errors;
let valid3 = false;
const _errs22 = errors;
if(typeof data8 !== "string"){
const err3 = {instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs22 === errors;
valid3 = valid3 || _valid1;
const _errs24 = errors;
if(data8 !== null){
const err4 = {instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs24 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs21;
if(vErrors !== null){
if(_errs21){
vErrors.length = _errs21;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trusted !== undefined){
const _errs26 = errors;
if(typeof data.trusted !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/trusted",schemaPath:"#/properties/trusted/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs26 === errors;
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
else {
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"props":{"contributions":true,"current_settings":true,"enabled":true,"healthy":true,"last_error":true,"loaded":true,"manifest":true,"package_sha256":true,"trusted":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginInstallCandidateResponse = validate90;
const schema38 = {"properties":{"archive_sha256":{"pattern":"^[0-9a-f]{64}$","title":"Archive Sha256","type":"string"},"candidate_id":{"title":"Candidate Id","type":"string"},"expires_at_ms":{"title":"Expires At Ms","type":"integer"},"manifest":{"$ref":"#/components/schemas/PluginManifestResponse"},"package_sha256":{"pattern":"^[0-9a-f]{64}$","title":"Package Sha256","type":"string"}},"required":["candidate_id","archive_sha256","package_sha256","expires_at_ms","manifest"],"title":"PluginInstallCandidateResponse","type":"object"};
const pattern7 = new RegExp("^[0-9a-f]{64}$", "u");

function validate90(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate90.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.candidate_id === undefined) && (missing0 = "candidate_id")) || ((data.archive_sha256 === undefined) && (missing0 = "archive_sha256"))) || ((data.package_sha256 === undefined) && (missing0 = "package_sha256"))) || ((data.expires_at_ms === undefined) && (missing0 = "expires_at_ms"))) || ((data.manifest === undefined) && (missing0 = "manifest"))){
validate90.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.archive_sha256 !== undefined){
let data0 = data.archive_sha256;
const _errs1 = errors;
if(errors === _errs1){
if(typeof data0 === "string"){
if(!pattern7.test(data0)){
validate90.errors = [{instancePath:instancePath+"/archive_sha256",schemaPath:"#/properties/archive_sha256/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate90.errors = [{instancePath:instancePath+"/archive_sha256",schemaPath:"#/properties/archive_sha256/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.candidate_id !== undefined){
const _errs3 = errors;
if(typeof data.candidate_id !== "string"){
validate90.errors = [{instancePath:instancePath+"/candidate_id",schemaPath:"#/properties/candidate_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.expires_at_ms !== undefined){
let data2 = data.expires_at_ms;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate90.errors = [{instancePath:instancePath+"/expires_at_ms",schemaPath:"#/properties/expires_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest !== undefined){
const _errs7 = errors;
if(!(validate69(data.manifest, {instancePath:instancePath+"/manifest",parentData:data,parentDataProperty:"manifest",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate69.errors : vErrors.concat(validate69.errors);
errors = vErrors.length;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.package_sha256 !== undefined){
let data4 = data.package_sha256;
const _errs8 = errors;
if(errors === _errs8){
if(typeof data4 === "string"){
if(!pattern7.test(data4)){
validate90.errors = [{instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate90.errors = [{instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate90.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate90.errors = vErrors;
return errors === 0;
}
validate90.evaluated = {"props":{"archive_sha256":true,"candidate_id":true,"expires_at_ms":true,"manifest":true,"package_sha256":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginInstallJobSnapshot = validate92;
const schema39 = {"properties":{"created_at_ms":{"title":"Created At Ms","type":"integer"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"error_code":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Code"},"filename":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Filename"},"finished_at_ms":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":null,"title":"Finished At Ms"},"job_id":{"title":"Job Id","type":"string"},"logs":{"items":{"$ref":"#/components/schemas/PluginInstallLogEntry"},"title":"Logs","type":"array"},"message":{"title":"Message","type":"string"},"operation":{"enum":["install","update","upload"],"title":"Operation","type":"string"},"plugin_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Plugin Id"},"progress_pct":{"default":0,"title":"Progress Pct","type":"number"},"result":{"anyOf":[{"$ref":"#/components/schemas/PluginPackageResponse"},{"type":"null"}],"default":null},"stage":{"title":"Stage","type":"string"},"status":{"enum":["queued","running","completed","failed"],"title":"Status","type":"string"},"updated_at_ms":{"title":"Updated At Ms","type":"integer"}},"required":["job_id","operation","plugin_id","filename","status","stage","progress_pct","message","error","error_code","logs","result","created_at_ms","updated_at_ms","finished_at_ms"],"title":"PluginInstallJobSnapshot","type":"object"};
const schema40 = {"properties":{"level":{"default":"info","enum":["info","warning","error"],"title":"Level","type":"string"},"message":{"title":"Message","type":"string"},"stage":{"title":"Stage","type":"string"},"ts_ms":{"title":"Ts Ms","type":"integer"}},"required":["ts_ms","level","stage","message"],"title":"PluginInstallLogEntry","type":"object"};

function validate93(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate93.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.ts_ms === undefined) && (missing0 = "ts_ms")) || ((data.level === undefined) && (missing0 = "level"))) || ((data.stage === undefined) && (missing0 = "stage"))) || ((data.message === undefined) && (missing0 = "message"))){
validate93.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.level !== undefined){
let data0 = data.level;
const _errs1 = errors;
if(typeof data0 !== "string"){
validate93.errors = [{instancePath:instancePath+"/level",schemaPath:"#/properties/level/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data0 === "info") || (data0 === "warning")) || (data0 === "error"))){
validate93.errors = [{instancePath:instancePath+"/level",schemaPath:"#/properties/level/enum",keyword:"enum",params:{allowedValues: schema40.properties.level.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs3 = errors;
if(typeof data.message !== "string"){
validate93.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.stage !== undefined){
const _errs5 = errors;
if(typeof data.stage !== "string"){
validate93.errors = [{instancePath:instancePath+"/stage",schemaPath:"#/properties/stage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ts_ms !== undefined){
let data3 = data.ts_ms;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate93.errors = [{instancePath:instancePath+"/ts_ms",schemaPath:"#/properties/ts_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate93.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate93.errors = vErrors;
return errors === 0;
}
validate93.evaluated = {"props":{"level":true,"message":true,"stage":true,"ts_ms":true},"dynamicProps":false,"dynamicItems":false};


function validate92(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate92.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((((((data.job_id === undefined) && (missing0 = "job_id")) || ((data.operation === undefined) && (missing0 = "operation"))) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.filename === undefined) && (missing0 = "filename"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.stage === undefined) && (missing0 = "stage"))) || ((data.progress_pct === undefined) && (missing0 = "progress_pct"))) || ((data.message === undefined) && (missing0 = "message"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.error_code === undefined) && (missing0 = "error_code"))) || ((data.logs === undefined) && (missing0 = "logs"))) || ((data.result === undefined) && (missing0 = "result"))) || ((data.created_at_ms === undefined) && (missing0 = "created_at_ms"))) || ((data.updated_at_ms === undefined) && (missing0 = "updated_at_ms"))) || ((data.finished_at_ms === undefined) && (missing0 = "finished_at_ms"))){
validate92.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.created_at_ms !== undefined){
let data0 = data.created_at_ms;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate92.errors = [{instancePath:instancePath+"/created_at_ms",schemaPath:"#/properties/created_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data1 = data.error;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate92.errors = vErrors;
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
if(data.error_code !== undefined){
let data2 = data.error_code;
const _errs9 = errors;
const _errs10 = errors;
let valid2 = false;
const _errs11 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
const _errs13 = errors;
if(data2 !== null){
const err4 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs13 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs10;
if(vErrors !== null){
if(_errs10){
vErrors.length = _errs10;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.filename !== undefined){
let data3 = data.filename;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
const _errs19 = errors;
if(data3 !== null){
const err7 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate92.errors = vErrors;
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
if(data.finished_at_ms !== undefined){
let data4 = data.finished_at_ms;
const _errs21 = errors;
const _errs22 = errors;
let valid4 = false;
const _errs23 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
const err9 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
const _errs25 = errors;
if(data4 !== null){
const err10 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs25 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs22;
if(vErrors !== null){
if(_errs22){
vErrors.length = _errs22;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.job_id !== undefined){
const _errs27 = errors;
if(typeof data.job_id !== "string"){
validate92.errors = [{instancePath:instancePath+"/job_id",schemaPath:"#/properties/job_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.logs !== undefined){
let data6 = data.logs;
const _errs29 = errors;
if(errors === _errs29){
if(Array.isArray(data6)){
var valid5 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs31 = errors;
if(!(validate93(data6[i0], {instancePath:instancePath+"/logs/" + i0,parentData:data6,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate93.errors : vErrors.concat(validate93.errors);
errors = vErrors.length;
}
var valid5 = _errs31 === errors;
if(!valid5){
break;
}
}
}
else {
validate92.errors = [{instancePath:instancePath+"/logs",schemaPath:"#/properties/logs/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs32 = errors;
if(typeof data.message !== "string"){
validate92.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.operation !== undefined){
let data9 = data.operation;
const _errs34 = errors;
if(typeof data9 !== "string"){
validate92.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data9 === "install") || (data9 === "update")) || (data9 === "upload"))){
validate92.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/enum",keyword:"enum",params:{allowedValues: schema39.properties.operation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
let data10 = data.plugin_id;
const _errs36 = errors;
const _errs37 = errors;
let valid6 = false;
const _errs38 = errors;
if(typeof data10 !== "string"){
const err12 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs38 === errors;
valid6 = valid6 || _valid4;
const _errs40 = errors;
if(data10 !== null){
const err13 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err14 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs37;
if(vErrors !== null){
if(_errs37){
vErrors.length = _errs37;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress_pct !== undefined){
const _errs42 = errors;
if(!(typeof data.progress_pct == "number")){
validate92.errors = [{instancePath:instancePath+"/progress_pct",schemaPath:"#/properties/progress_pct/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.result !== undefined){
let data12 = data.result;
const _errs44 = errors;
const _errs45 = errors;
let valid7 = false;
const _errs46 = errors;
if(!(validate62(data12, {instancePath:instancePath+"/result",parentData:data,parentDataProperty:"result",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var _valid5 = _errs46 === errors;
valid7 = valid7 || _valid5;
if(_valid5){
var props0 = {};
props0.contributions = true;
props0.current_settings = true;
props0.enabled = true;
props0.healthy = true;
props0.last_error = true;
props0.loaded = true;
props0.manifest = true;
props0.package_sha256 = true;
props0.trusted = true;
}
const _errs47 = errors;
if(data12 !== null){
const err15 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var _valid5 = _errs47 === errors;
valid7 = valid7 || _valid5;
if(!valid7){
const err16 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs45;
if(vErrors !== null){
if(_errs45){
vErrors.length = _errs45;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.stage !== undefined){
const _errs49 = errors;
if(typeof data.stage !== "string"){
validate92.errors = [{instancePath:instancePath+"/stage",schemaPath:"#/properties/stage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data14 = data.status;
const _errs51 = errors;
if(typeof data14 !== "string"){
validate92.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((data14 === "queued") || (data14 === "running")) || (data14 === "completed")) || (data14 === "failed"))){
validate92.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema39.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs51 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.updated_at_ms !== undefined){
let data15 = data.updated_at_ms;
const _errs53 = errors;
if(!((typeof data15 == "number") && (!(data15 % 1) && !isNaN(data15)))){
validate92.errors = [{instancePath:instancePath+"/updated_at_ms",schemaPath:"#/properties/updated_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs53 === errors;
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
}
else {
validate92.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate92.errors = vErrors;
return errors === 0;
}
validate92.evaluated = {"props":{"created_at_ms":true,"error":true,"error_code":true,"filename":true,"finished_at_ms":true,"job_id":true,"logs":true,"message":true,"operation":true,"plugin_id":true,"progress_pct":true,"result":true,"stage":true,"status":true,"updated_at_ms":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginRegistryResponse = validate96;
const schema41 = {"properties":{"install_fingerprint":{"pattern":"^[0-9a-f]{64}$","title":"Install Fingerprint","type":"string"},"plugins":{"items":{"$ref":"#/components/schemas/PluginRegistryEntryResponse"},"title":"Plugins","type":"array"},"registry_version":{"const":"4","title":"Registry Version","type":"string"}},"required":["plugins","registry_version","install_fingerprint"],"title":"PluginRegistryResponse","type":"object"};
const schema42 = {"properties":{"activation_flow":{"anyOf":[{"$ref":"#/components/schemas/ActivationFlowSpec"},{"type":"null"}],"default":null},"author":{"default":"","title":"Author","type":"string"},"capabilities":{"items":{"$ref":"#/components/schemas/PluginCapability"},"title":"Capabilities","type":"array"},"contribution_types":{"items":{"type":"string"},"title":"Contribution Types","type":"array"},"data_locality":{"default":"","title":"Data Locality","type":"string"},"description":{"default":"","title":"Description","type":"string"},"description_i18n":{"additionalProperties":{"type":"string"},"title":"Description I18N","type":"object"},"display_group":{"anyOf":[{"$ref":"#/components/schemas/PluginDisplayGroupSpec"},{"type":"null"}],"default":null},"execution_mode":{"enum":["restricted_process","trusted_process"],"title":"Execution Mode","type":"string"},"homepage":{"default":"","title":"Homepage","type":"string"},"icon":{"default":"","title":"Icon","type":"string"},"installed":{"default":false,"title":"Installed","type":"boolean"},"installed_version":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Installed Version"},"min_sdk_version":{"title":"Min Sdk Version","type":"string"},"name":{"title":"Name","type":"string"},"name_i18n":{"additionalProperties":{"type":"string"},"title":"Name I18N","type":"object"},"official":{"default":false,"title":"Official","type":"boolean"},"path":{"default":"","title":"Path","type":"string"},"platforms":{"items":{"type":"string"},"title":"Platforms","type":"array"},"plugin_id":{"title":"Plugin Id","type":"string"},"protocol_version":{"const":2,"title":"Protocol Version","type":"integer"},"repository":{"default":"","title":"Repository","type":"string"},"settings_actions":{"items":{"$ref":"#/components/schemas/PluginSettingsActionSpec"},"title":"Settings Actions","type":"array"},"settings_fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldSpec"},"title":"Settings Fields","type":"array"},"settings_resources":{"items":{"$ref":"#/components/schemas/PluginSettingsResourceSpec"},"title":"Settings Resources","type":"array"},"settings_ui_blocks":{"items":{"$ref":"#/components/schemas/SettingsUIBlockSpec"},"title":"Settings Ui Blocks","type":"array"},"update_available":{"default":false,"title":"Update Available","type":"boolean"},"version":{"title":"Version","type":"string"}},"required":["protocol_version","execution_mode","min_sdk_version","settings_fields","activation_flow","settings_actions","settings_resources","settings_ui_blocks","plugin_id","name","name_i18n","version","description","description_i18n","author","icon","display_group","official","data_locality","contribution_types","platforms","homepage","repository","path","installed","installed_version","update_available","capabilities"],"title":"PluginRegistryEntryResponse","type":"object"};
const schema43 = {"additionalProperties":false,"description":"Declarative first-enable flow rendered by the host UI.","properties":{"authorize_on_confirm":{"default":false,"title":"Authorize On Confirm","type":"boolean"},"cancel_label":{"default":"Cancel","title":"Cancel Label","type":"string"},"configured_key":{"title":"Configured Key","type":"string"},"confirm_label":{"default":"Confirm","title":"Confirm Label","type":"string"},"description":{"default":"","title":"Description","type":"string"},"enabled_key":{"title":"Enabled Key","type":"string"},"fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldSpec"},"title":"Fields","type":"array"},"first_context":{"anyOf":[{"$ref":"#/components/schemas/ActivationFirstContextSpec"},{"type":"null"}],"default":null},"title":{"title":"Title","type":"string"}},"required":["title","description","confirm_label","cancel_label","authorize_on_confirm","enabled_key","configured_key","fields","first_context"],"title":"ActivationFlowSpec","type":"object"};
const schema44 = {"additionalProperties":false,"description":"Declarative settings field exposed by a plugin contribution.","properties":{"default":{"default":null,"title":"Default"},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"key":{"title":"Key","type":"string"},"label":{"title":"Label","type":"string"},"maximum":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Maximum"},"minimum":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Minimum"},"options":{"items":{"$ref":"#/components/schemas/ExtensionFieldOption"},"title":"Options","type":"array"},"order":{"default":0,"title":"Order","type":"integer"},"path_kind":{"anyOf":[{"enum":["file","directory"],"type":"string"},{"type":"null"}],"default":null,"title":"Path Kind"},"placeholder":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Placeholder"},"required":{"default":false,"title":"Required","type":"boolean"},"section":{"default":"general","title":"Section","type":"string"},"surface":{"default":"extensions","enum":["extensions","tools","timeline"],"title":"Surface","type":"string"},"type":{"default":"input","enum":["switch","select","input","number","secret","path","tags"],"title":"Type","type":"string"}},"required":["key","type","path_kind","label","description","default","required","options","section","surface","order","placeholder","depends_on_key","depends_on_values","minimum","maximum"],"title":"ExtensionFieldSpec","type":"object"};
const schema45 = {"additionalProperties":false,"description":"Option for a select-like plugin field.","properties":{"label":{"title":"Label","type":"string"},"value":{"title":"Value","type":"string"}},"required":["label","value"],"title":"ExtensionFieldOption","type":"object"};

function validate100(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate100.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.label === undefined) && (missing0 = "label")) || ((data.value === undefined) && (missing0 = "value"))){
validate100.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((key0 === "label") || (key0 === "value"))){
validate100.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.label !== undefined){
const _errs2 = errors;
if(typeof data.label !== "string"){
validate100.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.value !== undefined){
const _errs4 = errors;
if(typeof data.value !== "string"){
validate100.errors = [{instancePath:instancePath+"/value",schemaPath:"#/properties/value/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate100.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate100.errors = vErrors;
return errors === 0;
}
validate100.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate99(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate99.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((data.key === undefined) && (missing0 = "key")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.path_kind === undefined) && (missing0 = "path_kind"))) || ((data.label === undefined) && (missing0 = "label"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.default === undefined) && (missing0 = "default"))) || ((data.required === undefined) && (missing0 = "required"))) || ((data.options === undefined) && (missing0 = "options"))) || ((data.section === undefined) && (missing0 = "section"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.placeholder === undefined) && (missing0 = "placeholder"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))) || ((data.minimum === undefined) && (missing0 = "minimum"))) || ((data.maximum === undefined) && (missing0 = "maximum"))){
validate99.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema44.properties, key0))){
validate99.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.depends_on_key !== undefined){
let data0 = data.depends_on_key;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const _errs6 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate99.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_values !== undefined){
let data1 = data.depends_on_values;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(typeof data1[i0] !== "string"){
validate99.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate99.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs12 = errors;
if(typeof data.description !== "string"){
validate99.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.key !== undefined){
const _errs14 = errors;
if(typeof data.key !== "string"){
validate99.errors = [{instancePath:instancePath+"/key",schemaPath:"#/properties/key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs16 = errors;
if(typeof data.label !== "string"){
validate99.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.maximum !== undefined){
let data6 = data.maximum;
const _errs18 = errors;
const _errs19 = errors;
let valid3 = false;
const _errs20 = errors;
if(!(typeof data6 == "number")){
const err3 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs20 === errors;
valid3 = valid3 || _valid1;
const _errs22 = errors;
if(data6 !== null){
const err4 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs22 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/maximum",schemaPath:"#/properties/maximum/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate99.errors = vErrors;
return false;
}
else {
errors = _errs19;
if(vErrors !== null){
if(_errs19){
vErrors.length = _errs19;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.minimum !== undefined){
let data7 = data.minimum;
const _errs24 = errors;
const _errs25 = errors;
let valid4 = false;
const _errs26 = errors;
if(!(typeof data7 == "number")){
const err6 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs26 === errors;
valid4 = valid4 || _valid2;
const _errs28 = errors;
if(data7 !== null){
const err7 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs28 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/minimum",schemaPath:"#/properties/minimum/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate99.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.options !== undefined){
let data8 = data.options;
const _errs30 = errors;
if(errors === _errs30){
if(Array.isArray(data8)){
var valid5 = true;
const len1 = data8.length;
for(let i1=0; i1<len1; i1++){
const _errs32 = errors;
if(!(validate100(data8[i1], {instancePath:instancePath+"/options/" + i1,parentData:data8,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate100.errors : vErrors.concat(validate100.errors);
errors = vErrors.length;
}
var valid5 = _errs32 === errors;
if(!valid5){
break;
}
}
}
else {
validate99.errors = [{instancePath:instancePath+"/options",schemaPath:"#/properties/options/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data10 = data.order;
const _errs33 = errors;
if(!((typeof data10 == "number") && (!(data10 % 1) && !isNaN(data10)))){
validate99.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path_kind !== undefined){
let data11 = data.path_kind;
const _errs35 = errors;
const _errs36 = errors;
let valid6 = false;
const _errs37 = errors;
if(typeof data11 !== "string"){
const err9 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
if(!((data11 === "file") || (data11 === "directory"))){
const err10 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/enum",keyword:"enum",params:{allowedValues: schema44.properties.path_kind.anyOf[0].enum},message:"must be equal to one of the allowed values"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs37 === errors;
valid6 = valid6 || _valid3;
const _errs39 = errors;
if(data11 !== null){
const err11 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid3 = _errs39 === errors;
valid6 = valid6 || _valid3;
if(!valid6){
const err12 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate99.errors = vErrors;
return false;
}
else {
errors = _errs36;
if(vErrors !== null){
if(_errs36){
vErrors.length = _errs36;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.placeholder !== undefined){
let data12 = data.placeholder;
const _errs41 = errors;
const _errs42 = errors;
let valid7 = false;
const _errs43 = errors;
if(typeof data12 !== "string"){
const err13 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs43 === errors;
valid7 = valid7 || _valid4;
const _errs45 = errors;
if(data12 !== null){
const err14 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid4 = _errs45 === errors;
valid7 = valid7 || _valid4;
if(!valid7){
const err15 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate99.errors = vErrors;
return false;
}
else {
errors = _errs42;
if(vErrors !== null){
if(_errs42){
vErrors.length = _errs42;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.required !== undefined){
const _errs47 = errors;
if(typeof data.required !== "boolean"){
validate99.errors = [{instancePath:instancePath+"/required",schemaPath:"#/properties/required/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section !== undefined){
const _errs49 = errors;
if(typeof data.section !== "string"){
validate99.errors = [{instancePath:instancePath+"/section",schemaPath:"#/properties/section/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data15 = data.surface;
const _errs51 = errors;
if(typeof data15 !== "string"){
validate99.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data15 === "extensions") || (data15 === "tools")) || (data15 === "timeline"))){
validate99.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema44.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs51 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data16 = data.type;
const _errs53 = errors;
if(typeof data16 !== "string"){
validate99.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data16 === "switch") || (data16 === "select")) || (data16 === "input")) || (data16 === "number")) || (data16 === "secret")) || (data16 === "path")) || (data16 === "tags"))){
validate99.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/enum",keyword:"enum",params:{allowedValues: schema44.properties.type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs53 === errors;
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
}
}
else {
validate99.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate99.errors = vErrors;
return errors === 0;
}
validate99.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate98(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate98.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((data.title === undefined) && (missing0 = "title")) || ((data.description === undefined) && (missing0 = "description"))) || ((data.confirm_label === undefined) && (missing0 = "confirm_label"))) || ((data.cancel_label === undefined) && (missing0 = "cancel_label"))) || ((data.authorize_on_confirm === undefined) && (missing0 = "authorize_on_confirm"))) || ((data.enabled_key === undefined) && (missing0 = "enabled_key"))) || ((data.configured_key === undefined) && (missing0 = "configured_key"))) || ((data.fields === undefined) && (missing0 = "fields"))) || ((data.first_context === undefined) && (missing0 = "first_context"))){
validate98.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema43.properties, key0))){
validate98.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.authorize_on_confirm !== undefined){
const _errs2 = errors;
if(typeof data.authorize_on_confirm !== "boolean"){
validate98.errors = [{instancePath:instancePath+"/authorize_on_confirm",schemaPath:"#/properties/authorize_on_confirm/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cancel_label !== undefined){
const _errs4 = errors;
if(typeof data.cancel_label !== "string"){
validate98.errors = [{instancePath:instancePath+"/cancel_label",schemaPath:"#/properties/cancel_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.configured_key !== undefined){
const _errs6 = errors;
if(typeof data.configured_key !== "string"){
validate98.errors = [{instancePath:instancePath+"/configured_key",schemaPath:"#/properties/configured_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.confirm_label !== undefined){
const _errs8 = errors;
if(typeof data.confirm_label !== "string"){
validate98.errors = [{instancePath:instancePath+"/confirm_label",schemaPath:"#/properties/confirm_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs10 = errors;
if(typeof data.description !== "string"){
validate98.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled_key !== undefined){
const _errs12 = errors;
if(typeof data.enabled_key !== "string"){
validate98.errors = [{instancePath:instancePath+"/enabled_key",schemaPath:"#/properties/enabled_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fields !== undefined){
let data6 = data.fields;
const _errs14 = errors;
if(errors === _errs14){
if(Array.isArray(data6)){
var valid1 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs16 = errors;
if(!(validate99(data6[i0], {instancePath:instancePath+"/fields/" + i0,parentData:data6,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate99.errors : vErrors.concat(validate99.errors);
errors = vErrors.length;
}
var valid1 = _errs16 === errors;
if(!valid1){
break;
}
}
}
else {
validate98.errors = [{instancePath:instancePath+"/fields",schemaPath:"#/properties/fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.first_context !== undefined){
let data8 = data.first_context;
const _errs17 = errors;
const _errs18 = errors;
let valid2 = false;
const _errs19 = errors;
if(!(validate72(data8, {instancePath:instancePath+"/first_context",parentData:data,parentDataProperty:"first_context",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate72.errors : vErrors.concat(validate72.errors);
errors = vErrors.length;
}
var _valid0 = _errs19 === errors;
valid2 = valid2 || _valid0;
const _errs20 = errors;
if(data8 !== null){
const err0 = {instancePath:instancePath+"/first_context",schemaPath:"#/properties/first_context/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs20 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err1 = {instancePath:instancePath+"/first_context",schemaPath:"#/properties/first_context/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate98.errors = vErrors;
return false;
}
else {
errors = _errs18;
if(vErrors !== null){
if(_errs18){
vErrors.length = _errs18;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs22 = errors;
if(typeof data.title !== "string"){
validate98.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
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
validate98.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate98.errors = vErrors;
return errors === 0;
}
validate98.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema46 = {"additionalProperties":false,"description":"Host-rendered settings action declared by a plugin.\n\nThe host owns routing and UI chrome, while the plugin owns the action\nimplementation and any provider-specific protocol details.","properties":{"action_id":{"title":"Action Id","type":"string"},"button_label":{"default":"Run","title":"Button Label","type":"string"},"contribution_id":{"default":"","title":"Contribution Id","type":"string"},"contribution_type":{"anyOf":[{"$ref":"#/components/schemas/ContributionType"},{"type":"null"}],"default":null},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"destructive":{"default":false,"title":"Destructive","type":"boolean"},"label":{"title":"Label","type":"string"},"order":{"default":0,"title":"Order","type":"integer"},"persist_settings_on_success":{"default":false,"title":"Persist Settings On Success","type":"boolean"},"poll_interval_ms":{"default":2000,"maximum":60000,"minimum":100,"title":"Poll Interval Ms","type":"integer"},"presentation":{"default":"inline","enum":["inline","qr_code"],"title":"Presentation","type":"string"},"requires_enabled":{"default":true,"title":"Requires Enabled","type":"boolean"},"surface":{"default":"extensions","enum":["extensions","tools","timeline"],"title":"Surface","type":"string"},"timeout_ms":{"default":480000,"maximum":3600000,"minimum":1,"title":"Timeout Ms","type":"integer"}},"required":["action_id","label","description","button_label","presentation","surface","contribution_id","contribution_type","order","destructive","requires_enabled","poll_interval_ms","timeout_ms","persist_settings_on_success","depends_on_key","depends_on_values"],"title":"PluginSettingsActionSpec","type":"object"};

function validate107(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate107.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((data.action_id === undefined) && (missing0 = "action_id")) || ((data.label === undefined) && (missing0 = "label"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.button_label === undefined) && (missing0 = "button_label"))) || ((data.presentation === undefined) && (missing0 = "presentation"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.contribution_id === undefined) && (missing0 = "contribution_id"))) || ((data.contribution_type === undefined) && (missing0 = "contribution_type"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.destructive === undefined) && (missing0 = "destructive"))) || ((data.requires_enabled === undefined) && (missing0 = "requires_enabled"))) || ((data.poll_interval_ms === undefined) && (missing0 = "poll_interval_ms"))) || ((data.timeout_ms === undefined) && (missing0 = "timeout_ms"))) || ((data.persist_settings_on_success === undefined) && (missing0 = "persist_settings_on_success"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))){
validate107.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema46.properties, key0))){
validate107.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.action_id !== undefined){
const _errs2 = errors;
if(typeof data.action_id !== "string"){
validate107.errors = [{instancePath:instancePath+"/action_id",schemaPath:"#/properties/action_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.button_label !== undefined){
const _errs4 = errors;
if(typeof data.button_label !== "string"){
validate107.errors = [{instancePath:instancePath+"/button_label",schemaPath:"#/properties/button_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_id !== undefined){
const _errs6 = errors;
if(typeof data.contribution_id !== "string"){
validate107.errors = [{instancePath:instancePath+"/contribution_id",schemaPath:"#/properties/contribution_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_type !== undefined){
let data3 = data.contribution_type;
const _errs8 = errors;
const _errs9 = errors;
let valid1 = false;
const _errs10 = errors;
if(!(validate81(data3, {instancePath:instancePath+"/contribution_type",parentData:data,parentDataProperty:"contribution_type",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate81.errors : vErrors.concat(validate81.errors);
errors = vErrors.length;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
const _errs11 = errors;
if(data3 !== null){
const err0 = {instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs11 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate107.errors = vErrors;
return false;
}
else {
errors = _errs9;
if(vErrors !== null){
if(_errs9){
vErrors.length = _errs9;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_key !== undefined){
let data4 = data.depends_on_key;
const _errs13 = errors;
const _errs14 = errors;
let valid2 = false;
const _errs15 = errors;
if(typeof data4 !== "string"){
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid2 = valid2 || _valid1;
const _errs17 = errors;
if(data4 !== null){
const err3 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate107.errors = vErrors;
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
if(data.depends_on_values !== undefined){
let data5 = data.depends_on_values;
const _errs19 = errors;
if(errors === _errs19){
if(Array.isArray(data5)){
var valid3 = true;
const len0 = data5.length;
for(let i0=0; i0<len0; i0++){
const _errs21 = errors;
if(typeof data5[i0] !== "string"){
validate107.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs21 === errors;
if(!valid3){
break;
}
}
}
else {
validate107.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs23 = errors;
if(typeof data.description !== "string"){
validate107.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.destructive !== undefined){
const _errs25 = errors;
if(typeof data.destructive !== "boolean"){
validate107.errors = [{instancePath:instancePath+"/destructive",schemaPath:"#/properties/destructive/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs27 = errors;
if(typeof data.label !== "string"){
validate107.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data10 = data.order;
const _errs29 = errors;
if(!((typeof data10 == "number") && (!(data10 % 1) && !isNaN(data10)))){
validate107.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persist_settings_on_success !== undefined){
const _errs31 = errors;
if(typeof data.persist_settings_on_success !== "boolean"){
validate107.errors = [{instancePath:instancePath+"/persist_settings_on_success",schemaPath:"#/properties/persist_settings_on_success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.poll_interval_ms !== undefined){
let data12 = data.poll_interval_ms;
const _errs33 = errors;
if(!((typeof data12 == "number") && (!(data12 % 1) && !isNaN(data12)))){
validate107.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs33){
if(typeof data12 == "number"){
if(data12 > 60000 || isNaN(data12)){
validate107.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/maximum",keyword:"maximum",params:{comparison: "<=", limit: 60000},message:"must be <= 60000"}];
return false;
}
else {
if(data12 < 100 || isNaN(data12)){
validate107.errors = [{instancePath:instancePath+"/poll_interval_ms",schemaPath:"#/properties/poll_interval_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 100},message:"must be >= 100"}];
return false;
}
}
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.presentation !== undefined){
let data13 = data.presentation;
const _errs35 = errors;
if(typeof data13 !== "string"){
validate107.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data13 === "inline") || (data13 === "qr_code"))){
validate107.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/enum",keyword:"enum",params:{allowedValues: schema46.properties.presentation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.requires_enabled !== undefined){
const _errs37 = errors;
if(typeof data.requires_enabled !== "boolean"){
validate107.errors = [{instancePath:instancePath+"/requires_enabled",schemaPath:"#/properties/requires_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data15 = data.surface;
const _errs39 = errors;
if(typeof data15 !== "string"){
validate107.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data15 === "extensions") || (data15 === "tools")) || (data15 === "timeline"))){
validate107.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema46.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timeout_ms !== undefined){
let data16 = data.timeout_ms;
const _errs41 = errors;
if(!((typeof data16 == "number") && (!(data16 % 1) && !isNaN(data16)))){
validate107.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs41){
if(typeof data16 == "number"){
if(data16 > 3600000 || isNaN(data16)){
validate107.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/maximum",keyword:"maximum",params:{comparison: "<=", limit: 3600000},message:"must be <= 3600000"}];
return false;
}
else {
if(data16 < 1 || isNaN(data16)){
validate107.errors = [{instancePath:instancePath+"/timeout_ms",schemaPath:"#/properties/timeout_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs41 === errors;
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
}
}
}
else {
validate107.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate107.errors = vErrors;
return errors === 0;
}
validate107.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema47 = {"additionalProperties":false,"description":"Host-rendered custom settings block declared by a plugin.\n\nBlocks are read-only or selection widgets whose underlying data comes from a\n``PluginSettingsResourceSpec``. The ``presentation`` hint tells the host\nwhich widget to render. New presentations may be added over time as the\nplugin platform matures.\n\n``value_key`` is only meaningful for blocks that bind a selection back to a\nsettings field (e.g. ``calendar_list``). Read-only presentations like\n``permission_status`` ignore it; plugins should still pass a stable value\nsuch as ``\"_readonly\"`` to keep the schema stable.","properties":{"block_id":{"title":"Block Id","type":"string"},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"presentation":{"default":"list","enum":["calendar_list","list","permission_status"],"title":"Presentation","type":"string"},"resource_name":{"title":"Resource Name","type":"string"},"title":{"title":"Title","type":"string"},"type":{"const":"resource_picker","default":"resource_picker","title":"Type","type":"string"},"value_key":{"title":"Value Key","type":"string"}},"required":["block_id","type","title","description","resource_name","value_key","presentation","depends_on_key","depends_on_values"],"title":"SettingsUIBlockSpec","type":"object"};

function validate112(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate112.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((data.block_id === undefined) && (missing0 = "block_id")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.title === undefined) && (missing0 = "title"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.resource_name === undefined) && (missing0 = "resource_name"))) || ((data.value_key === undefined) && (missing0 = "value_key"))) || ((data.presentation === undefined) && (missing0 = "presentation"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))){
validate112.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema47.properties, key0))){
validate112.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.block_id !== undefined){
const _errs2 = errors;
if(typeof data.block_id !== "string"){
validate112.errors = [{instancePath:instancePath+"/block_id",schemaPath:"#/properties/block_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_key !== undefined){
let data1 = data.depends_on_key;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate112.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.depends_on_values !== undefined){
let data2 = data.depends_on_values;
const _errs10 = errors;
if(errors === _errs10){
if(Array.isArray(data2)){
var valid2 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs12 = errors;
if(typeof data2[i0] !== "string"){
validate112.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs12 === errors;
if(!valid2){
break;
}
}
}
else {
validate112.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs14 = errors;
if(typeof data.description !== "string"){
validate112.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.presentation !== undefined){
let data5 = data.presentation;
const _errs16 = errors;
if(typeof data5 !== "string"){
validate112.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data5 === "calendar_list") || (data5 === "list")) || (data5 === "permission_status"))){
validate112.errors = [{instancePath:instancePath+"/presentation",schemaPath:"#/properties/presentation/enum",keyword:"enum",params:{allowedValues: schema47.properties.presentation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_name !== undefined){
const _errs18 = errors;
if(typeof data.resource_name !== "string"){
validate112.errors = [{instancePath:instancePath+"/resource_name",schemaPath:"#/properties/resource_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs20 = errors;
if(typeof data.title !== "string"){
validate112.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data8 = data.type;
const _errs22 = errors;
if(typeof data8 !== "string"){
validate112.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("resource_picker" !== data8){
validate112.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/const",keyword:"const",params:{allowedValue: "resource_picker"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.value_key !== undefined){
const _errs24 = errors;
if(typeof data.value_key !== "string"){
validate112.errors = [{instancePath:instancePath+"/value_key",schemaPath:"#/properties/value_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
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
else {
validate112.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate112.errors = vErrors;
return errors === 0;
}
validate112.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate97(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate97.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((((((((((((((data.protocol_version === undefined) && (missing0 = "protocol_version")) || ((data.execution_mode === undefined) && (missing0 = "execution_mode"))) || ((data.min_sdk_version === undefined) && (missing0 = "min_sdk_version"))) || ((data.settings_fields === undefined) && (missing0 = "settings_fields"))) || ((data.activation_flow === undefined) && (missing0 = "activation_flow"))) || ((data.settings_actions === undefined) && (missing0 = "settings_actions"))) || ((data.settings_resources === undefined) && (missing0 = "settings_resources"))) || ((data.settings_ui_blocks === undefined) && (missing0 = "settings_ui_blocks"))) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.name === undefined) && (missing0 = "name"))) || ((data.name_i18n === undefined) && (missing0 = "name_i18n"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.description_i18n === undefined) && (missing0 = "description_i18n"))) || ((data.author === undefined) && (missing0 = "author"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.display_group === undefined) && (missing0 = "display_group"))) || ((data.official === undefined) && (missing0 = "official"))) || ((data.data_locality === undefined) && (missing0 = "data_locality"))) || ((data.contribution_types === undefined) && (missing0 = "contribution_types"))) || ((data.platforms === undefined) && (missing0 = "platforms"))) || ((data.homepage === undefined) && (missing0 = "homepage"))) || ((data.repository === undefined) && (missing0 = "repository"))) || ((data.path === undefined) && (missing0 = "path"))) || ((data.installed === undefined) && (missing0 = "installed"))) || ((data.installed_version === undefined) && (missing0 = "installed_version"))) || ((data.update_available === undefined) && (missing0 = "update_available"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))){
validate97.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.activation_flow !== undefined){
let data0 = data.activation_flow;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate98(data0, {instancePath:instancePath+"/activation_flow",parentData:data,parentDataProperty:"activation_flow",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate98.errors : vErrors.concat(validate98.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/activation_flow",schemaPath:"#/properties/activation_flow/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err1 = {instancePath:instancePath+"/activation_flow",schemaPath:"#/properties/activation_flow/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate97.errors = vErrors;
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
if(data.author !== undefined){
const _errs6 = errors;
if(typeof data.author !== "string"){
validate97.errors = [{instancePath:instancePath+"/author",schemaPath:"#/properties/author/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.capabilities !== undefined){
let data2 = data.capabilities;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data2)){
var valid2 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(!(validate75(data2[i0], {instancePath:instancePath+"/capabilities/" + i0,parentData:data2,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate75.errors : vErrors.concat(validate75.errors);
errors = vErrors.length;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/capabilities",schemaPath:"#/properties/capabilities/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_types !== undefined){
let data4 = data.contribution_types;
const _errs11 = errors;
if(errors === _errs11){
if(Array.isArray(data4)){
var valid3 = true;
const len1 = data4.length;
for(let i1=0; i1<len1; i1++){
const _errs13 = errors;
if(typeof data4[i1] !== "string"){
validate97.errors = [{instancePath:instancePath+"/contribution_types/" + i1,schemaPath:"#/properties/contribution_types/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs13 === errors;
if(!valid3){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/contribution_types",schemaPath:"#/properties/contribution_types/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data_locality !== undefined){
const _errs15 = errors;
if(typeof data.data_locality !== "string"){
validate97.errors = [{instancePath:instancePath+"/data_locality",schemaPath:"#/properties/data_locality/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs17 = errors;
if(typeof data.description !== "string"){
validate97.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_i18n !== undefined){
let data8 = data.description_i18n;
const _errs19 = errors;
if(errors === _errs19){
if(data8 && typeof data8 == "object" && !Array.isArray(data8)){
for(const key0 in data8){
const _errs22 = errors;
if(typeof data8[key0] !== "string"){
validate97.errors = [{instancePath:instancePath+"/description_i18n/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/description_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid4 = _errs22 === errors;
if(!valid4){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/description_i18n",schemaPath:"#/properties/description_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_group !== undefined){
let data10 = data.display_group;
const _errs24 = errors;
const _errs25 = errors;
let valid5 = false;
const _errs26 = errors;
if(!(validate78(data10, {instancePath:instancePath+"/display_group",parentData:data,parentDataProperty:"display_group",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate78.errors : vErrors.concat(validate78.errors);
errors = vErrors.length;
}
var _valid1 = _errs26 === errors;
valid5 = valid5 || _valid1;
const _errs27 = errors;
if(data10 !== null){
const err2 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs27 === errors;
valid5 = valid5 || _valid1;
if(!valid5){
const err3 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate97.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.execution_mode !== undefined){
let data11 = data.execution_mode;
const _errs29 = errors;
if(typeof data11 !== "string"){
validate97.errors = [{instancePath:instancePath+"/execution_mode",schemaPath:"#/properties/execution_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data11 === "restricted_process") || (data11 === "trusted_process"))){
validate97.errors = [{instancePath:instancePath+"/execution_mode",schemaPath:"#/properties/execution_mode/enum",keyword:"enum",params:{allowedValues: schema42.properties.execution_mode.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.homepage !== undefined){
const _errs31 = errors;
if(typeof data.homepage !== "string"){
validate97.errors = [{instancePath:instancePath+"/homepage",schemaPath:"#/properties/homepage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
const _errs33 = errors;
if(typeof data.icon !== "string"){
validate97.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.installed !== undefined){
const _errs35 = errors;
if(typeof data.installed !== "boolean"){
validate97.errors = [{instancePath:instancePath+"/installed",schemaPath:"#/properties/installed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.installed_version !== undefined){
let data15 = data.installed_version;
const _errs37 = errors;
const _errs38 = errors;
let valid6 = false;
const _errs39 = errors;
if(typeof data15 !== "string"){
const err4 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid2 = _errs39 === errors;
valid6 = valid6 || _valid2;
const _errs41 = errors;
if(data15 !== null){
const err5 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid2 = _errs41 === errors;
valid6 = valid6 || _valid2;
if(!valid6){
const err6 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
validate97.errors = vErrors;
return false;
}
else {
errors = _errs38;
if(vErrors !== null){
if(_errs38){
vErrors.length = _errs38;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.min_sdk_version !== undefined){
const _errs43 = errors;
if(typeof data.min_sdk_version !== "string"){
validate97.errors = [{instancePath:instancePath+"/min_sdk_version",schemaPath:"#/properties/min_sdk_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs45 = errors;
if(typeof data.name !== "string"){
validate97.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name_i18n !== undefined){
let data18 = data.name_i18n;
const _errs47 = errors;
if(errors === _errs47){
if(data18 && typeof data18 == "object" && !Array.isArray(data18)){
for(const key1 in data18){
const _errs50 = errors;
if(typeof data18[key1] !== "string"){
validate97.errors = [{instancePath:instancePath+"/name_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/name_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid7 = _errs50 === errors;
if(!valid7){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/name_i18n",schemaPath:"#/properties/name_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.official !== undefined){
const _errs52 = errors;
if(typeof data.official !== "boolean"){
validate97.errors = [{instancePath:instancePath+"/official",schemaPath:"#/properties/official/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs52 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path !== undefined){
const _errs54 = errors;
if(typeof data.path !== "string"){
validate97.errors = [{instancePath:instancePath+"/path",schemaPath:"#/properties/path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs54 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.platforms !== undefined){
let data22 = data.platforms;
const _errs56 = errors;
if(errors === _errs56){
if(Array.isArray(data22)){
var valid8 = true;
const len2 = data22.length;
for(let i2=0; i2<len2; i2++){
const _errs58 = errors;
if(typeof data22[i2] !== "string"){
validate97.errors = [{instancePath:instancePath+"/platforms/" + i2,schemaPath:"#/properties/platforms/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid8 = _errs58 === errors;
if(!valid8){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/platforms",schemaPath:"#/properties/platforms/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs56 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs60 = errors;
if(typeof data.plugin_id !== "string"){
validate97.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs60 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol_version !== undefined){
let data25 = data.protocol_version;
const _errs62 = errors;
if(!((typeof data25 == "number") && (!(data25 % 1) && !isNaN(data25)))){
validate97.errors = [{instancePath:instancePath+"/protocol_version",schemaPath:"#/properties/protocol_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(2 !== data25){
validate97.errors = [{instancePath:instancePath+"/protocol_version",schemaPath:"#/properties/protocol_version/const",keyword:"const",params:{allowedValue: 2},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs62 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.repository !== undefined){
const _errs64 = errors;
if(typeof data.repository !== "string"){
validate97.errors = [{instancePath:instancePath+"/repository",schemaPath:"#/properties/repository/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs64 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_actions !== undefined){
let data27 = data.settings_actions;
const _errs66 = errors;
if(errors === _errs66){
if(Array.isArray(data27)){
var valid9 = true;
const len3 = data27.length;
for(let i3=0; i3<len3; i3++){
const _errs68 = errors;
if(!(validate107(data27[i3], {instancePath:instancePath+"/settings_actions/" + i3,parentData:data27,parentDataProperty:i3,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate107.errors : vErrors.concat(validate107.errors);
errors = vErrors.length;
}
var valid9 = _errs68 === errors;
if(!valid9){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/settings_actions",schemaPath:"#/properties/settings_actions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs66 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_fields !== undefined){
let data29 = data.settings_fields;
const _errs69 = errors;
if(errors === _errs69){
if(Array.isArray(data29)){
var valid10 = true;
const len4 = data29.length;
for(let i4=0; i4<len4; i4++){
const _errs71 = errors;
if(!(validate99(data29[i4], {instancePath:instancePath+"/settings_fields/" + i4,parentData:data29,parentDataProperty:i4,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate99.errors : vErrors.concat(validate99.errors);
errors = vErrors.length;
}
var valid10 = _errs71 === errors;
if(!valid10){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/settings_fields",schemaPath:"#/properties/settings_fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs69 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_resources !== undefined){
let data31 = data.settings_resources;
const _errs72 = errors;
if(errors === _errs72){
if(Array.isArray(data31)){
var valid11 = true;
const len5 = data31.length;
for(let i5=0; i5<len5; i5++){
const _errs74 = errors;
if(!(validate85(data31[i5], {instancePath:instancePath+"/settings_resources/" + i5,parentData:data31,parentDataProperty:i5,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate85.errors : vErrors.concat(validate85.errors);
errors = vErrors.length;
}
var valid11 = _errs74 === errors;
if(!valid11){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/settings_resources",schemaPath:"#/properties/settings_resources/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs72 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_ui_blocks !== undefined){
let data33 = data.settings_ui_blocks;
const _errs75 = errors;
if(errors === _errs75){
if(Array.isArray(data33)){
var valid12 = true;
const len6 = data33.length;
for(let i6=0; i6<len6; i6++){
const _errs77 = errors;
if(!(validate112(data33[i6], {instancePath:instancePath+"/settings_ui_blocks/" + i6,parentData:data33,parentDataProperty:i6,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate112.errors : vErrors.concat(validate112.errors);
errors = vErrors.length;
}
var valid12 = _errs77 === errors;
if(!valid12){
break;
}
}
}
else {
validate97.errors = [{instancePath:instancePath+"/settings_ui_blocks",schemaPath:"#/properties/settings_ui_blocks/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs75 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.update_available !== undefined){
const _errs78 = errors;
if(typeof data.update_available !== "boolean"){
validate97.errors = [{instancePath:instancePath+"/update_available",schemaPath:"#/properties/update_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs78 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
const _errs80 = errors;
if(typeof data.version !== "string"){
validate97.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs80 === errors;
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
validate97.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate97.errors = vErrors;
return errors === 0;
}
validate97.evaluated = {"props":{"activation_flow":true,"author":true,"capabilities":true,"contribution_types":true,"data_locality":true,"description":true,"description_i18n":true,"display_group":true,"execution_mode":true,"homepage":true,"icon":true,"installed":true,"installed_version":true,"min_sdk_version":true,"name":true,"name_i18n":true,"official":true,"path":true,"platforms":true,"plugin_id":true,"protocol_version":true,"repository":true,"settings_actions":true,"settings_fields":true,"settings_resources":true,"settings_ui_blocks":true,"update_available":true,"version":true},"dynamicProps":false,"dynamicItems":false};


function validate96(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate96.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.plugins === undefined) && (missing0 = "plugins")) || ((data.registry_version === undefined) && (missing0 = "registry_version"))) || ((data.install_fingerprint === undefined) && (missing0 = "install_fingerprint"))){
validate96.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.install_fingerprint !== undefined){
let data0 = data.install_fingerprint;
const _errs1 = errors;
if(errors === _errs1){
if(typeof data0 === "string"){
if(!pattern7.test(data0)){
validate96.errors = [{instancePath:instancePath+"/install_fingerprint",schemaPath:"#/properties/install_fingerprint/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate96.errors = [{instancePath:instancePath+"/install_fingerprint",schemaPath:"#/properties/install_fingerprint/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugins !== undefined){
let data1 = data.plugins;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate97(data1[i0], {instancePath:instancePath+"/plugins/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate97.errors : vErrors.concat(validate97.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate96.errors = [{instancePath:instancePath+"/plugins",schemaPath:"#/properties/plugins/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.registry_version !== undefined){
let data3 = data.registry_version;
const _errs6 = errors;
if(typeof data3 !== "string"){
validate96.errors = [{instancePath:instancePath+"/registry_version",schemaPath:"#/properties/registry_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("4" !== data3){
validate96.errors = [{instancePath:instancePath+"/registry_version",schemaPath:"#/properties/registry_version/const",keyword:"const",params:{allowedValue: "4"},message:"must be equal to constant"}];
return false;
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
validate96.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate96.errors = vErrors;
return errors === 0;
}
validate96.evaluated = {"props":{"install_fingerprint":true,"plugins":true,"registry_version":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginSettingsActionRunResponse = validate115;
const schema48 = {"properties":{"action_id":{"title":"Action Id","type":"string"},"connection_id":{"title":"Connection Id","type":"string"},"data":{"additionalProperties":true,"title":"Data","type":"object"},"message":{"default":"","title":"Message","type":"string"},"plugin_id":{"title":"Plugin Id","type":"string"},"session_id":{"title":"Session Id","type":"string"},"settings_updates":{"additionalProperties":true,"title":"Settings Updates","type":"object"},"status":{"enum":["pending","succeeded","failed","cancelled","uncertain"],"title":"Status","type":"string"}},"required":["connection_id","plugin_id","action_id","session_id","status","message","data","settings_updates"],"title":"PluginSettingsActionRunResponse","type":"object"};

function validate115(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate115.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((data.connection_id === undefined) && (missing0 = "connection_id")) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.action_id === undefined) && (missing0 = "action_id"))) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.message === undefined) && (missing0 = "message"))) || ((data.data === undefined) && (missing0 = "data"))) || ((data.settings_updates === undefined) && (missing0 = "settings_updates"))){
validate115.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.action_id !== undefined){
const _errs1 = errors;
if(typeof data.action_id !== "string"){
validate115.errors = [{instancePath:instancePath+"/action_id",schemaPath:"#/properties/action_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.connection_id !== undefined){
const _errs3 = errors;
if(typeof data.connection_id !== "string"){
validate115.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
let data2 = data.data;
const _errs5 = errors;
if(errors === _errs5){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
validate115.errors = [{instancePath:instancePath+"/data",schemaPath:"#/properties/data/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs8 = errors;
if(typeof data.message !== "string"){
validate115.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs10 = errors;
if(typeof data.plugin_id !== "string"){
validate115.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs12 = errors;
if(typeof data.session_id !== "string"){
validate115.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_updates !== undefined){
let data6 = data.settings_updates;
const _errs14 = errors;
if(errors === _errs14){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
}
else {
validate115.errors = [{instancePath:instancePath+"/settings_updates",schemaPath:"#/properties/settings_updates/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data7 = data.status;
const _errs17 = errors;
if(typeof data7 !== "string"){
validate115.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data7 === "pending") || (data7 === "succeeded")) || (data7 === "failed")) || (data7 === "cancelled")) || (data7 === "uncertain"))){
validate115.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema48.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs17 === errors;
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
validate115.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate115.errors = vErrors;
return errors === 0;
}
validate115.evaluated = {"props":{"action_id":true,"connection_id":true,"data":true,"message":true,"plugin_id":true,"session_id":true,"settings_updates":true,"status":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginSettingsResourceResponse = validate116;
const schema49 = {"properties":{"connection_id":{"title":"Connection Id","type":"string"},"data":{"default":null,"title":"Data"},"plugin_id":{"title":"Plugin Id","type":"string"},"resource_name":{"title":"Resource Name","type":"string"},"resource_type":{"title":"Resource Type","type":"string"}},"required":["connection_id","plugin_id","resource_name","resource_type","data"],"title":"PluginSettingsResourceResponse","type":"object"};

function validate116(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate116.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.connection_id === undefined) && (missing0 = "connection_id")) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.resource_name === undefined) && (missing0 = "resource_name"))) || ((data.resource_type === undefined) && (missing0 = "resource_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate116.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.connection_id !== undefined){
const _errs1 = errors;
if(typeof data.connection_id !== "string"){
validate116.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs3 = errors;
if(typeof data.plugin_id !== "string"){
validate116.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_name !== undefined){
const _errs5 = errors;
if(typeof data.resource_name !== "string"){
validate116.errors = [{instancePath:instancePath+"/resource_name",schemaPath:"#/properties/resource_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_type !== undefined){
const _errs7 = errors;
if(typeof data.resource_type !== "string"){
validate116.errors = [{instancePath:instancePath+"/resource_type",schemaPath:"#/properties/resource_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate116.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate116.errors = vErrors;
return errors === 0;
}
validate116.evaluated = {"props":{"connection_id":true,"data":true,"plugin_id":true,"resource_name":true,"resource_type":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginsListResponse = validate117;
const schema50 = {"properties":{"plugins":{"items":{"$ref":"#/components/schemas/PluginPackageResponse"},"title":"Plugins","type":"array"},"total":{"title":"Total","type":"integer"}},"required":["plugins","total"],"title":"PluginsListResponse","type":"object"};

function validate117(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate117.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.plugins === undefined) && (missing0 = "plugins")) || ((data.total === undefined) && (missing0 = "total"))){
validate117.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.plugins !== undefined){
let data0 = data.plugins;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate62(data0[i0], {instancePath:instancePath+"/plugins/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate117.errors = [{instancePath:instancePath+"/plugins",schemaPath:"#/properties/plugins/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total !== undefined){
let data2 = data.total;
const _errs4 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate117.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate117.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate117.errors = vErrors;
return errors === 0;
}
validate117.evaluated = {"props":{"plugins":true,"total":true},"dynamicProps":false,"dynamicItems":false};
