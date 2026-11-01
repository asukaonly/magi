// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateCollectionCapability = validate53;
const schema20 = {"additionalProperties":false,"properties":{"capability_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Capability Id","type":"string"},"direction":{"const":"observe","default":"observe","title":"Direction","type":"string"},"payload_schema":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"title":"Payload Schema","type":"object"},"protocol":{"const":"source.change.v1","title":"Protocol","type":"string"},"schema_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Schema Id","type":"string"},"schema_version":{"maximum":2147483647,"minimum":1,"title":"Schema Version","type":"integer"},"supports_resources":{"const":false,"default":false,"title":"Supports Resources","type":"boolean"}},"required":["capability_id","protocol","schema_id","schema_version","payload_schema"],"title":"CollectionCapability","type":"object"};
const func1 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });
const pattern3 = new RegExp("^[A-Za-z0-9._:-]+$", "u");
const schema21 = {};

function validate54(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
validate54.errors = null;
return true;
}
validate54.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if((((((data.capability_id === undefined) && (missing0 = "capability_id")) || ((data.protocol === undefined) && (missing0 = "protocol"))) || ((data.schema_id === undefined) && (missing0 = "schema_id"))) || ((data.schema_version === undefined) && (missing0 = "schema_version"))) || ((data.payload_schema === undefined) && (missing0 = "payload_schema"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "capability_id") || (key0 === "direction")) || (key0 === "payload_schema")) || (key0 === "protocol")) || (key0 === "schema_id")) || (key0 === "schema_version")) || (key0 === "supports_resources"))){
validate53.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
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
validate53.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate53.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate53.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.direction !== undefined){
let data1 = data.direction;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate53.errors = [{instancePath:instancePath+"/direction",schemaPath:"#/properties/direction/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("observe" !== data1){
validate53.errors = [{instancePath:instancePath+"/direction",schemaPath:"#/properties/direction/const",keyword:"const",params:{allowedValue: "observe"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload_schema !== undefined){
let data2 = data.payload_schema;
const _errs6 = errors;
if(errors === _errs6){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
for(const key1 in data2){
const _errs9 = errors;
if(!(validate54(data2[key1], {instancePath:instancePath+"/payload_schema/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data2,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid1 = _errs9 === errors;
if(!valid1){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/payload_schema",schemaPath:"#/properties/payload_schema/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol !== undefined){
let data4 = data.protocol;
const _errs10 = errors;
if(typeof data4 !== "string"){
validate53.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("source.change.v1" !== data4){
validate53.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/const",keyword:"const",params:{allowedValue: "source.change.v1"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_id !== undefined){
let data5 = data.schema_id;
const _errs12 = errors;
if(errors === _errs12){
if(typeof data5 === "string"){
if(func1(data5) > 128){
validate53.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data5) < 1){
validate53.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data5)){
validate53.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_version !== undefined){
let data6 = data.schema_version;
const _errs14 = errors;
if(!((typeof data6 == "number") && (!(data6 % 1) && !isNaN(data6)))){
validate53.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs14){
if(typeof data6 == "number"){
if(data6 > 2147483647 || isNaN(data6)){
validate53.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2147483647},message:"must be <= 2147483647"}];
return false;
}
else {
if(data6 < 1 || isNaN(data6)){
validate53.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.supports_resources !== undefined){
let data7 = data.supports_resources;
const _errs16 = errors;
if(typeof data7 !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/supports_resources",schemaPath:"#/properties/supports_resources/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
if(false !== data7){
validate53.errors = [{instancePath:instancePath+"/supports_resources",schemaPath:"#/properties/supports_resources/const",keyword:"const",params:{allowedValue: false},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs16 === errors;
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
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateCollectorScope = validate56;
const schema22 = {"additionalProperties":false,"properties":{"capability":{"$ref":"#/components/schemas/CollectionCapability"},"claimed_by":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Claimed By"},"connection_epoch":{"format":"uuid","title":"Connection Epoch","type":"string"},"connection_id":{"title":"Connection Id","type":"string"},"source_type":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Source Type","type":"string"}},"required":["connection_id","connection_epoch","source_type","capability","claimed_by"],"title":"CollectorScope","type":"object"};
const formats0 = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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
if((((((data.connection_id === undefined) && (missing0 = "connection_id")) || ((data.connection_epoch === undefined) && (missing0 = "connection_epoch"))) || ((data.source_type === undefined) && (missing0 = "source_type"))) || ((data.capability === undefined) && (missing0 = "capability"))) || ((data.claimed_by === undefined) && (missing0 = "claimed_by"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "capability") || (key0 === "claimed_by")) || (key0 === "connection_epoch")) || (key0 === "connection_id")) || (key0 === "source_type"))){
validate56.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.capability !== undefined){
const _errs2 = errors;
if(!(validate53(data.capability, {instancePath:instancePath+"/capability",parentData:data,parentDataProperty:"capability",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.claimed_by !== undefined){
let data1 = data.claimed_by;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/claimed_by",schemaPath:"#/properties/claimed_by/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/claimed_by",schemaPath:"#/properties/claimed_by/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/claimed_by",schemaPath:"#/properties/claimed_by/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.connection_epoch !== undefined){
let data2 = data.connection_epoch;
const _errs9 = errors;
if(errors === _errs9){
if(errors === _errs9){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate56.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate56.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
if(data.connection_id !== undefined){
const _errs11 = errors;
if(typeof data.connection_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_type !== undefined){
let data4 = data.source_type;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data4 === "string"){
if(func1(data4) > 128){
validate56.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data4) < 1){
validate56.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data4)){
validate56.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateCollectorClaim = validate58;
const schema23 = {"additionalProperties":false,"properties":{"capability_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Capability Id","type":"string"},"connection_epoch":{"format":"uuid","title":"Connection Epoch","type":"string"},"protocol":{"const":"source.change.v1","title":"Protocol","type":"string"},"schema_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Schema Id","type":"string"},"schema_version":{"maximum":2147483647,"minimum":1,"title":"Schema Version","type":"integer"}},"required":["capability_id","protocol","schema_id","schema_version","connection_epoch"],"title":"CollectorClaim","type":"object"};

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
if((((((data.capability_id === undefined) && (missing0 = "capability_id")) || ((data.protocol === undefined) && (missing0 = "protocol"))) || ((data.schema_id === undefined) && (missing0 = "schema_id"))) || ((data.schema_version === undefined) && (missing0 = "schema_version"))) || ((data.connection_epoch === undefined) && (missing0 = "connection_epoch"))){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "capability_id") || (key0 === "connection_epoch")) || (key0 === "protocol")) || (key0 === "schema_id")) || (key0 === "schema_version"))){
validate58.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
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
validate58.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate58.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate58.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.connection_epoch !== undefined){
let data1 = data.connection_epoch;
const _errs4 = errors;
if(errors === _errs4){
if(errors === _errs4){
if(typeof data1 === "string"){
if(!(formats0.test(data1))){
validate58.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate58.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol !== undefined){
let data2 = data.protocol;
const _errs6 = errors;
if(typeof data2 !== "string"){
validate58.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("source.change.v1" !== data2){
validate58.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/const",keyword:"const",params:{allowedValue: "source.change.v1"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_id !== undefined){
let data3 = data.schema_id;
const _errs8 = errors;
if(errors === _errs8){
if(typeof data3 === "string"){
if(func1(data3) > 128){
validate58.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate58.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data3)){
validate58.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_version !== undefined){
let data4 = data.schema_version;
const _errs10 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate58.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs10){
if(typeof data4 == "number"){
if(data4 > 2147483647 || isNaN(data4)){
validate58.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2147483647},message:"must be <= 2147483647"}];
return false;
}
else {
if(data4 < 1 || isNaN(data4)){
validate58.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
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
validate58.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate58.errors = vErrors;
return errors === 0;
}
validate58.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateCapabilityIdentity = validate59;
const schema24 = {"additionalProperties":false,"properties":{"capability_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Capability Id","type":"string"},"protocol":{"const":"source.change.v1","title":"Protocol","type":"string"},"schema_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Schema Id","type":"string"},"schema_version":{"maximum":2147483647,"minimum":1,"title":"Schema Version","type":"integer"}},"required":["capability_id","protocol","schema_id","schema_version"],"title":"CapabilityIdentity","type":"object"};

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
if(((((data.capability_id === undefined) && (missing0 = "capability_id")) || ((data.protocol === undefined) && (missing0 = "protocol"))) || ((data.schema_id === undefined) && (missing0 = "schema_id"))) || ((data.schema_version === undefined) && (missing0 = "schema_version"))){
validate59.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "capability_id") || (key0 === "protocol")) || (key0 === "schema_id")) || (key0 === "schema_version"))){
validate59.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
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
validate59.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate59.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate59.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol !== undefined){
let data1 = data.protocol;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate59.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("source.change.v1" !== data1){
validate59.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/const",keyword:"const",params:{allowedValue: "source.change.v1"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_id !== undefined){
let data2 = data.schema_id;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 === "string"){
if(func1(data2) > 128){
validate59.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data2) < 1){
validate59.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data2)){
validate59.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_version !== undefined){
let data3 = data.schema_version;
const _errs8 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate59.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs8){
if(typeof data3 == "number"){
if(data3 > 2147483647 || isNaN(data3)){
validate59.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2147483647},message:"must be <= 2147483647"}];
return false;
}
else {
if(data3 < 1 || isNaN(data3)){
validate59.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
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
validate59.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate59.errors = vErrors;
return errors === 0;
}
validate59.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateSourceObservation = validate60;
const schema25 = {"additionalProperties":false,"properties":{"capability_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Capability Id","type":"string"},"change":{"$ref":"#/components/schemas/ObservationChange"},"connection_epoch":{"format":"uuid","title":"Connection Epoch","type":"string"},"connection_id":{"pattern":"^conn_[0-9a-f]{32}$","title":"Connection Id","type":"string"},"kind":{"type":"string","enum":["source_observation"],"description":"discriminator enum property added by openapi-typescript"},"protocol":{"const":"source.change.v1","title":"Protocol","type":"string"},"schema_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Schema Id","type":"string"},"schema_version":{"maximum":2147483647,"minimum":1,"title":"Schema Version","type":"integer"},"source_type":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Source Type","type":"string"}},"required":["capability_id","protocol","schema_id","schema_version","kind","connection_id","connection_epoch","source_type","change"],"title":"SourceObservation","type":"object"};
const func15 = Object.prototype.hasOwnProperty;
const pattern13 = new RegExp("^conn_[0-9a-f]{32}$", "u");
const schema26 = {"additionalProperties":false,"properties":{"object_id":{"maxLength":1024,"minLength":1,"title":"Object Id","type":"string"},"occurred_at":{"anyOf":[{"type":"number"},{"type":"null"}],"title":"Occurred At"},"operation":{"default":"upsert","enum":["upsert","delete"],"title":"Operation","type":"string"},"payload":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"title":"Payload","type":"object"},"resources":{"items":{"$ref":"#/components/schemas/ResourceRef"},"maxItems":0,"title":"Resources","type":"array"},"version":{"maxLength":256,"minLength":1,"title":"Version","type":"string"}},"required":["object_id","version"],"title":"ObservationChange","type":"object"};
const schema27 = {"additionalProperties":false,"description":"Opaque, revocable reference to host-managed content.","properties":{"connection_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Connection Id","type":"string"},"display_name":{"default":"","maxLength":512,"title":"Display Name","type":"string"},"media_type":{"maxLength":256,"minLength":1,"title":"Media Type","type":"string"},"resource_id":{"maxLength":128,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Resource Id","type":"string"},"size_bytes":{"minimum":0,"title":"Size Bytes","type":"integer"},"version":{"maxLength":256,"minLength":1,"title":"Version","type":"string"}},"required":["resource_id","connection_id","media_type","size_bytes","version"],"title":"ResourceRef","type":"object"};
const pattern11 = new RegExp("^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$", "u");

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
if((((((data.resource_id === undefined) && (missing0 = "resource_id")) || ((data.connection_id === undefined) && (missing0 = "connection_id"))) || ((data.media_type === undefined) && (missing0 = "media_type"))) || ((data.size_bytes === undefined) && (missing0 = "size_bytes"))) || ((data.version === undefined) && (missing0 = "version"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "connection_id") || (key0 === "display_name")) || (key0 === "media_type")) || (key0 === "resource_id")) || (key0 === "size_bytes")) || (key0 === "version"))){
validate63.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
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
validate63.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate63.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern11.test(data0)){
validate63.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
let data1 = data.display_name;
const _errs4 = errors;
if(errors === _errs4){
if(typeof data1 === "string"){
if(func1(data1) > 512){
validate63.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/maxLength",keyword:"maxLength",params:{limit: 512},message:"must NOT have more than 512 characters"}];
return false;
}
}
else {
validate63.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.media_type !== undefined){
let data2 = data.media_type;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 === "string"){
if(func1(data2) > 256){
validate63.errors = [{instancePath:instancePath+"/media_type",schemaPath:"#/properties/media_type/maxLength",keyword:"maxLength",params:{limit: 256},message:"must NOT have more than 256 characters"}];
return false;
}
else {
if(func1(data2) < 1){
validate63.errors = [{instancePath:instancePath+"/media_type",schemaPath:"#/properties/media_type/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/media_type",schemaPath:"#/properties/media_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_id !== undefined){
let data3 = data.resource_id;
const _errs8 = errors;
if(errors === _errs8){
if(typeof data3 === "string"){
if(func1(data3) > 128){
validate63.errors = [{instancePath:instancePath+"/resource_id",schemaPath:"#/properties/resource_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate63.errors = [{instancePath:instancePath+"/resource_id",schemaPath:"#/properties/resource_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern11.test(data3)){
validate63.errors = [{instancePath:instancePath+"/resource_id",schemaPath:"#/properties/resource_id/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/resource_id",schemaPath:"#/properties/resource_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.size_bytes !== undefined){
let data4 = data.size_bytes;
const _errs10 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate63.errors = [{instancePath:instancePath+"/size_bytes",schemaPath:"#/properties/size_bytes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs10){
if(typeof data4 == "number"){
if(data4 < 0 || isNaN(data4)){
validate63.errors = [{instancePath:instancePath+"/size_bytes",schemaPath:"#/properties/size_bytes/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
let data5 = data.version;
const _errs12 = errors;
if(errors === _errs12){
if(typeof data5 === "string"){
if(func1(data5) > 256){
validate63.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/maxLength",keyword:"maxLength",params:{limit: 256},message:"must NOT have more than 256 characters"}];
return false;
}
else {
if(func1(data5) < 1){
validate63.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs12 === errors;
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
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate61(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate61.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.object_id === undefined) && (missing0 = "object_id")) || ((data.version === undefined) && (missing0 = "version"))){
validate61.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "object_id") || (key0 === "occurred_at")) || (key0 === "operation")) || (key0 === "payload")) || (key0 === "resources")) || (key0 === "version"))){
validate61.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.object_id !== undefined){
let data0 = data.object_id;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func1(data0) > 1024){
validate61.errors = [{instancePath:instancePath+"/object_id",schemaPath:"#/properties/object_id/maxLength",keyword:"maxLength",params:{limit: 1024},message:"must NOT have more than 1024 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate61.errors = [{instancePath:instancePath+"/object_id",schemaPath:"#/properties/object_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/object_id",schemaPath:"#/properties/object_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.occurred_at !== undefined){
let data1 = data.occurred_at;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(!(typeof data1 == "number")){
const err0 = {instancePath:instancePath+"/occurred_at",schemaPath:"#/properties/occurred_at/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
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
const err1 = {instancePath:instancePath+"/occurred_at",schemaPath:"#/properties/occurred_at/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/occurred_at",schemaPath:"#/properties/occurred_at/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate61.errors = vErrors;
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
if(data.operation !== undefined){
let data2 = data.operation;
const _errs10 = errors;
if(typeof data2 !== "string"){
validate61.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data2 === "upsert") || (data2 === "delete"))){
validate61.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/enum",keyword:"enum",params:{allowedValues: schema26.properties.operation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data3 = data.payload;
const _errs12 = errors;
if(errors === _errs12){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key1 in data3){
const _errs15 = errors;
if(!(validate54(data3[key1], {instancePath:instancePath+"/payload/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data3,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid2 = _errs15 === errors;
if(!valid2){
break;
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resources !== undefined){
let data5 = data.resources;
const _errs16 = errors;
if(errors === _errs16){
if(Array.isArray(data5)){
if(data5.length > 0){
validate61.errors = [{instancePath:instancePath+"/resources",schemaPath:"#/properties/resources/maxItems",keyword:"maxItems",params:{limit: 0},message:"must NOT have more than 0 items"}];
return false;
}
else {
var valid3 = true;
const len0 = data5.length;
for(let i0=0; i0<len0; i0++){
const _errs18 = errors;
if(!(validate63(data5[i0], {instancePath:instancePath+"/resources/" + i0,parentData:data5,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate63.errors : vErrors.concat(validate63.errors);
errors = vErrors.length;
}
var valid3 = _errs18 === errors;
if(!valid3){
break;
}
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/resources",schemaPath:"#/properties/resources/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
let data7 = data.version;
const _errs19 = errors;
if(errors === _errs19){
if(typeof data7 === "string"){
if(func1(data7) > 256){
validate61.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/maxLength",keyword:"maxLength",params:{limit: 256},message:"must NOT have more than 256 characters"}];
return false;
}
else {
if(func1(data7) < 1){
validate61.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs19 === errors;
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
validate61.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate61.errors = vErrors;
return errors === 0;
}
validate61.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((((((((data.capability_id === undefined) && (missing0 = "capability_id")) || ((data.protocol === undefined) && (missing0 = "protocol"))) || ((data.schema_id === undefined) && (missing0 = "schema_id"))) || ((data.schema_version === undefined) && (missing0 = "schema_version"))) || ((data.kind === undefined) && (missing0 = "kind"))) || ((data.connection_id === undefined) && (missing0 = "connection_id"))) || ((data.connection_epoch === undefined) && (missing0 = "connection_epoch"))) || ((data.source_type === undefined) && (missing0 = "source_type"))) || ((data.change === undefined) && (missing0 = "change"))){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func15.call(schema25.properties, key0))){
validate60.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
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
validate60.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate60.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate60.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/capability_id",schemaPath:"#/properties/capability_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.change !== undefined){
const _errs4 = errors;
if(!(validate61(data.change, {instancePath:instancePath+"/change",parentData:data,parentDataProperty:"change",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate61.errors : vErrors.concat(validate61.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.connection_epoch !== undefined){
let data2 = data.connection_epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate60.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate60.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.connection_id !== undefined){
let data3 = data.connection_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(!pattern13.test(data3)){
validate60.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/pattern",keyword:"pattern",params:{pattern: "^conn_[0-9a-f]{32}$"},message:"must match pattern \""+"^conn_[0-9a-f]{32}$"+"\""}];
return false;
}
}
else {
validate60.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data4 = data.kind;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate60.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "source_observation")){
validate60.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema25.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.protocol !== undefined){
let data5 = data.protocol;
const _errs11 = errors;
if(typeof data5 !== "string"){
validate60.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("source.change.v1" !== data5){
validate60.errors = [{instancePath:instancePath+"/protocol",schemaPath:"#/properties/protocol/const",keyword:"const",params:{allowedValue: "source.change.v1"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_id !== undefined){
let data6 = data.schema_id;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data6 === "string"){
if(func1(data6) > 128){
validate60.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data6) < 1){
validate60.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data6)){
validate60.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/schema_id",schemaPath:"#/properties/schema_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.schema_version !== undefined){
let data7 = data.schema_version;
const _errs15 = errors;
if(!((typeof data7 == "number") && (!(data7 % 1) && !isNaN(data7)))){
validate60.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs15){
if(typeof data7 == "number"){
if(data7 > 2147483647 || isNaN(data7)){
validate60.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/maximum",keyword:"maximum",params:{comparison: "<=", limit: 2147483647},message:"must be <= 2147483647"}];
return false;
}
else {
if(data7 < 1 || isNaN(data7)){
validate60.errors = [{instancePath:instancePath+"/schema_version",schemaPath:"#/properties/schema_version/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_type !== undefined){
let data8 = data.source_type;
const _errs17 = errors;
if(errors === _errs17){
if(typeof data8 === "string"){
if(func1(data8) > 128){
validate60.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data8) < 1){
validate60.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data8)){
validate60.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
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
validate60.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateDeliveryBatch = validate66;
const schema28 = {"additionalProperties":false,"properties":{"data_epoch":{"format":"uuid","title":"Data Epoch","type":"string"},"events":{"items":{"$ref":"#/components/schemas/BackgroundEvent"},"maxItems":32,"minItems":1,"title":"Events","type":"array"},"producer_id":{"format":"uuid","title":"Producer Id","type":"string"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["server_id","data_epoch","producer_id","events"],"title":"DeliveryBatch","type":"object"};
const schema29 = {"additionalProperties":false,"properties":{"event_id":{"format":"uuid","title":"Event Id","type":"string"},"occurred_at_ms":{"maximum":9223372036854776000,"minimum":0,"title":"Occurred At Ms","type":"integer"},"payload":{"discriminator":{"mapping":{"notification_read":"#/components/schemas/NotificationRead","plugin_event":"#/components/schemas/PluginEvent","source_observation":"#/components/schemas/SourceObservation"},"propertyName":"kind"},"oneOf":[{"$ref":"#/components/schemas/PluginEvent"},{"$ref":"#/components/schemas/NotificationRead"},{"$ref":"#/components/schemas/SourceObservation"}],"title":"Payload"},"sequence":{"exclusiveMinimum":0,"maximum":9223372036854776000,"title":"Sequence","type":"integer"},"stream":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Stream","type":"string"}},"required":["event_id","stream","sequence","occurred_at_ms","payload"],"title":"BackgroundEvent","type":"object"};
const schema30 = {"additionalProperties":false,"properties":{"connection_epoch":{"format":"uuid","title":"Connection Epoch","type":"string"},"connection_id":{"pattern":"^conn_[0-9a-f]{32}$","title":"Connection Id","type":"string"},"data":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"title":"Data","type":"object"},"event_type":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Event Type","type":"string"},"kind":{"type":"string","enum":["plugin_event"],"description":"discriminator enum property added by openapi-typescript"},"plugin_target":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]+$","title":"Plugin Target","type":"string"}},"required":["kind","connection_id","connection_epoch","plugin_target","event_type","data"],"title":"PluginEvent","type":"object"};

function validate68(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate68.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.kind === undefined) && (missing0 = "kind")) || ((data.connection_id === undefined) && (missing0 = "connection_id"))) || ((data.connection_epoch === undefined) && (missing0 = "connection_epoch"))) || ((data.plugin_target === undefined) && (missing0 = "plugin_target"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "connection_epoch") || (key0 === "connection_id")) || (key0 === "data")) || (key0 === "event_type")) || (key0 === "kind")) || (key0 === "plugin_target"))){
validate68.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.connection_epoch !== undefined){
let data0 = data.connection_epoch;
const _errs2 = errors;
if(errors === _errs2){
if(errors === _errs2){
if(typeof data0 === "string"){
if(!(formats0.test(data0))){
validate68.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate68.errors = [{instancePath:instancePath+"/connection_epoch",schemaPath:"#/properties/connection_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
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
if(!pattern13.test(data1)){
validate68.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/pattern",keyword:"pattern",params:{pattern: "^conn_[0-9a-f]{32}$"},message:"must match pattern \""+"^conn_[0-9a-f]{32}$"+"\""}];
return false;
}
}
else {
validate68.errors = [{instancePath:instancePath+"/connection_id",schemaPath:"#/properties/connection_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
let data2 = data.data;
const _errs6 = errors;
if(errors === _errs6){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
for(const key1 in data2){
const _errs9 = errors;
if(!(validate54(data2[key1], {instancePath:instancePath+"/data/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data2,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid1 = _errs9 === errors;
if(!valid1){
break;
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/data",schemaPath:"#/properties/data/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs10 = errors;
if(errors === _errs10){
if(typeof data4 === "string"){
if(func1(data4) > 128){
validate68.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data4) < 1){
validate68.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data4)){
validate68.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data5 = data.kind;
const _errs12 = errors;
if(typeof data5 !== "string"){
validate68.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data5 === "plugin_event")){
validate68.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema30.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_target !== undefined){
let data6 = data.plugin_target;
const _errs14 = errors;
if(errors === _errs14){
if(typeof data6 === "string"){
if(func1(data6) > 128){
validate68.errors = [{instancePath:instancePath+"/plugin_target",schemaPath:"#/properties/plugin_target/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data6) < 1){
validate68.errors = [{instancePath:instancePath+"/plugin_target",schemaPath:"#/properties/plugin_target/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data6)){
validate68.errors = [{instancePath:instancePath+"/plugin_target",schemaPath:"#/properties/plugin_target/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/plugin_target",schemaPath:"#/properties/plugin_target/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs14 === errors;
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
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema31 = {"additionalProperties":false,"properties":{"kind":{"type":"string","enum":["notification_read"],"description":"discriminator enum property added by openapi-typescript"},"notification_id":{"exclusiveMinimum":0,"maximum":9007199254740991,"title":"Notification Id","type":"integer"}},"required":["kind","notification_id"],"title":"NotificationRead","type":"object"};

function validate71(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate71.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.kind === undefined) && (missing0 = "kind")) || ((data.notification_id === undefined) && (missing0 = "notification_id"))){
validate71.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((key0 === "kind") || (key0 === "notification_id"))){
validate71.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.kind !== undefined){
let data0 = data.kind;
const _errs2 = errors;
if(typeof data0 !== "string"){
validate71.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data0 === "notification_read")){
validate71.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema31.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.notification_id !== undefined){
let data1 = data.notification_id;
const _errs4 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate71.errors = [{instancePath:instancePath+"/notification_id",schemaPath:"#/properties/notification_id/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs4){
if(typeof data1 == "number"){
if(data1 > 9007199254740991 || isNaN(data1)){
validate71.errors = [{instancePath:instancePath+"/notification_id",schemaPath:"#/properties/notification_id/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data1 <= 0 || isNaN(data1)){
validate71.errors = [{instancePath:instancePath+"/notification_id",schemaPath:"#/properties/notification_id/exclusiveMinimum",keyword:"exclusiveMinimum",params:{comparison: ">", limit: 0},message:"must be > 0"}];
return false;
}
}
}
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
validate71.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate71.errors = vErrors;
return errors === 0;
}
validate71.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate67(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate67.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.event_id === undefined) && (missing0 = "event_id")) || ((data.stream === undefined) && (missing0 = "stream"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.occurred_at_ms === undefined) && (missing0 = "occurred_at_ms"))) || ((data.payload === undefined) && (missing0 = "payload"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "event_id") || (key0 === "occurred_at_ms")) || (key0 === "payload")) || (key0 === "sequence")) || (key0 === "stream"))){
validate67.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.event_id !== undefined){
let data0 = data.event_id;
const _errs2 = errors;
if(errors === _errs2){
if(errors === _errs2){
if(typeof data0 === "string"){
if(!(formats0.test(data0))){
validate67.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate67.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.occurred_at_ms !== undefined){
let data1 = data.occurred_at_ms;
const _errs4 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate67.errors = [{instancePath:instancePath+"/occurred_at_ms",schemaPath:"#/properties/occurred_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs4){
if(typeof data1 == "number"){
if(data1 > 9223372036854776000 || isNaN(data1)){
validate67.errors = [{instancePath:instancePath+"/occurred_at_ms",schemaPath:"#/properties/occurred_at_ms/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9223372036854776000},message:"must be <= 9223372036854776000"}];
return false;
}
else {
if(data1 < 0 || isNaN(data1)){
validate67.errors = [{instancePath:instancePath+"/occurred_at_ms",schemaPath:"#/properties/occurred_at_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data2 = data.payload;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
let passing0 = null;
const _errs8 = errors;
if(!(validate68(data2, {instancePath:instancePath+"/payload",parentData:data,parentDataProperty:"payload",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate68.errors : vErrors.concat(validate68.errors);
errors = vErrors.length;
}
var _valid0 = _errs8 === errors;
if(_valid0){
valid1 = true;
passing0 = 0;
var props0 = true;
}
const _errs9 = errors;
if(!(validate71(data2, {instancePath:instancePath+"/payload",parentData:data,parentDataProperty:"payload",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate71.errors : vErrors.concat(validate71.errors);
errors = vErrors.length;
}
var _valid0 = _errs9 === errors;
if(_valid0 && valid1){
valid1 = false;
passing0 = [passing0, 1];
}
else {
if(_valid0){
valid1 = true;
passing0 = 1;
if(props0 !== true){
props0 = true;
}
}
const _errs10 = errors;
if(!(validate60(data2, {instancePath:instancePath+"/payload",parentData:data,parentDataProperty:"payload",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var _valid0 = _errs10 === errors;
if(_valid0 && valid1){
valid1 = false;
passing0 = [passing0, 2];
}
else {
if(_valid0){
valid1 = true;
passing0 = 2;
if(props0 !== true){
props0 = true;
}
}
}
}
if(!valid1){
const err0 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/oneOf",keyword:"oneOf",params:{passingSchemas: passing0},message:"must match exactly one schema in oneOf"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
validate67.errors = vErrors;
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
if(data.sequence !== undefined){
let data3 = data.sequence;
const _errs11 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data3 == "number"){
if(data3 > 9223372036854776000 || isNaN(data3)){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9223372036854776000},message:"must be <= 9223372036854776000"}];
return false;
}
else {
if(data3 <= 0 || isNaN(data3)){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/exclusiveMinimum",keyword:"exclusiveMinimum",params:{comparison: ">", limit: 0},message:"must be > 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.stream !== undefined){
let data4 = data.stream;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data4 === "string"){
if(func1(data4) > 128){
validate67.errors = [{instancePath:instancePath+"/stream",schemaPath:"#/properties/stream/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func1(data4) < 1){
validate67.errors = [{instancePath:instancePath+"/stream",schemaPath:"#/properties/stream/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data4)){
validate67.errors = [{instancePath:instancePath+"/stream",schemaPath:"#/properties/stream/pattern",keyword:"pattern",params:{pattern: "^[A-Za-z0-9._:-]+$"},message:"must match pattern \""+"^[A-Za-z0-9._:-]+$"+"\""}];
return false;
}
}
}
}
else {
validate67.errors = [{instancePath:instancePath+"/stream",schemaPath:"#/properties/stream/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate66(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate66.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.server_id === undefined) && (missing0 = "server_id")) || ((data.data_epoch === undefined) && (missing0 = "data_epoch"))) || ((data.producer_id === undefined) && (missing0 = "producer_id"))) || ((data.events === undefined) && (missing0 = "events"))){
validate66.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "data_epoch") || (key0 === "events")) || (key0 === "producer_id")) || (key0 === "server_id"))){
validate66.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.data_epoch !== undefined){
let data0 = data.data_epoch;
const _errs2 = errors;
if(errors === _errs2){
if(errors === _errs2){
if(typeof data0 === "string"){
if(!(formats0.test(data0))){
validate66.errors = [{instancePath:instancePath+"/data_epoch",schemaPath:"#/properties/data_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate66.errors = [{instancePath:instancePath+"/data_epoch",schemaPath:"#/properties/data_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.events !== undefined){
let data1 = data.events;
const _errs4 = errors;
if(errors === _errs4){
if(Array.isArray(data1)){
if(data1.length > 32){
validate66.errors = [{instancePath:instancePath+"/events",schemaPath:"#/properties/events/maxItems",keyword:"maxItems",params:{limit: 32},message:"must NOT have more than 32 items"}];
return false;
}
else {
if(data1.length < 1){
validate66.errors = [{instancePath:instancePath+"/events",schemaPath:"#/properties/events/minItems",keyword:"minItems",params:{limit: 1},message:"must NOT have fewer than 1 items"}];
return false;
}
else {
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs6 = errors;
if(!(validate67(data1[i0], {instancePath:instancePath+"/events/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate67.errors : vErrors.concat(validate67.errors);
errors = vErrors.length;
}
var valid1 = _errs6 === errors;
if(!valid1){
break;
}
}
}
}
}
else {
validate66.errors = [{instancePath:instancePath+"/events",schemaPath:"#/properties/events/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.producer_id !== undefined){
let data3 = data.producer_id;
const _errs7 = errors;
if(errors === _errs7){
if(errors === _errs7){
if(typeof data3 === "string"){
if(!(formats0.test(data3))){
validate66.errors = [{instancePath:instancePath+"/producer_id",schemaPath:"#/properties/producer_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate66.errors = [{instancePath:instancePath+"/producer_id",schemaPath:"#/properties/producer_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data4 = data.server_id;
const _errs9 = errors;
if(errors === _errs9){
if(errors === _errs9){
if(typeof data4 === "string"){
if(!(formats0.test(data4))){
validate66.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate66.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs9 === errors;
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
validate66.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate66.errors = vErrors;
return errors === 0;
}
validate66.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateDeliveryReceipt = validate75;
const schema32 = {"additionalProperties":false,"properties":{"data_epoch":{"format":"uuid","title":"Data Epoch","type":"string"},"receipts":{"items":{"$ref":"#/components/schemas/EventReceipt"},"title":"Receipts","type":"array"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["server_id","data_epoch","receipts"],"title":"DeliveryReceipt","type":"object"};
const schema33 = {"additionalProperties":false,"properties":{"code":{"title":"Code","type":"string"},"event_id":{"format":"uuid","title":"Event Id","type":"string"},"status":{"enum":["accepted","retry","rejected"],"title":"Status","type":"string"}},"required":["event_id","status","code"],"title":"EventReceipt","type":"object"};

function validate76(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate76.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.event_id === undefined) && (missing0 = "event_id")) || ((data.status === undefined) && (missing0 = "status"))) || ((data.code === undefined) && (missing0 = "code"))){
validate76.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "code") || (key0 === "event_id")) || (key0 === "status"))){
validate76.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.code !== undefined){
const _errs2 = errors;
if(typeof data.code !== "string"){
validate76.errors = [{instancePath:instancePath+"/code",schemaPath:"#/properties/code/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data1 = data.event_id;
const _errs4 = errors;
if(errors === _errs4){
if(errors === _errs4){
if(typeof data1 === "string"){
if(!(formats0.test(data1))){
validate76.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate76.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data2 = data.status;
const _errs6 = errors;
if(typeof data2 !== "string"){
validate76.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data2 === "accepted") || (data2 === "retry")) || (data2 === "rejected"))){
validate76.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema33.properties.status.enum},message:"must be equal to one of the allowed values"}];
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
}
else {
validate76.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate76.errors = vErrors;
return errors === 0;
}
validate76.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((data.server_id === undefined) && (missing0 = "server_id")) || ((data.data_epoch === undefined) && (missing0 = "data_epoch"))) || ((data.receipts === undefined) && (missing0 = "receipts"))){
validate75.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "data_epoch") || (key0 === "receipts")) || (key0 === "server_id"))){
validate75.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.data_epoch !== undefined){
let data0 = data.data_epoch;
const _errs2 = errors;
if(errors === _errs2){
if(errors === _errs2){
if(typeof data0 === "string"){
if(!(formats0.test(data0))){
validate75.errors = [{instancePath:instancePath+"/data_epoch",schemaPath:"#/properties/data_epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate75.errors = [{instancePath:instancePath+"/data_epoch",schemaPath:"#/properties/data_epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.receipts !== undefined){
let data1 = data.receipts;
const _errs4 = errors;
if(errors === _errs4){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs6 = errors;
if(!(validate76(data1[i0], {instancePath:instancePath+"/receipts/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate76.errors : vErrors.concat(validate76.errors);
errors = vErrors.length;
}
var valid1 = _errs6 === errors;
if(!valid1){
break;
}
}
}
else {
validate75.errors = [{instancePath:instancePath+"/receipts",schemaPath:"#/properties/receipts/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data3 = data.server_id;
const _errs7 = errors;
if(errors === _errs7){
if(errors === _errs7){
if(typeof data3 === "string"){
if(!(formats0.test(data3))){
validate75.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate75.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
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
validate75.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate75.errors = vErrors;
return errors === 0;
}
validate75.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};
