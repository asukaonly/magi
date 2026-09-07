// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateChatDisplayMessage = validate53;
const schema20 = {"description":"Typed read model for chat history and display timeline messages.","properties":{"allow_trace_collapse":{"default":false,"title":"Allow Trace Collapse","type":"boolean"},"attachments":{"anyOf":[{"items":{"additionalProperties":true,"type":"object"},"type":"array"},{"type":"null"}],"default":null,"title":"Attachments"},"content":{"title":"Content","type":"string"},"kind":{"title":"Kind","type":"string"},"label":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Label"},"message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Id"},"message_kind":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Kind"},"payload":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Payload"},"persona_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Persona Id"},"reply_to":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Reply To"},"role":{"title":"Role","type":"string"},"run_state":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Run State"},"timestamp":{"title":"Timestamp","type":"integer"},"trace_available":{"default":false,"title":"Trace Available","type":"boolean"},"trace_display_mode":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Trace Display Mode"},"trace_summary":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Trace Summary"},"turn_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Turn Id"}},"required":["role","content","timestamp","kind","attachments","message_id","message_kind","persona_id","turn_id","trace_display_mode","allow_trace_collapse","trace_summary","trace_available","run_state","reply_to","label","payload"],"title":"ChatDisplayMessage","type":"object"};

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
if((((((((((((((((((data.role === undefined) && (missing0 = "role")) || ((data.content === undefined) && (missing0 = "content"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))) || ((data.kind === undefined) && (missing0 = "kind"))) || ((data.attachments === undefined) && (missing0 = "attachments"))) || ((data.message_id === undefined) && (missing0 = "message_id"))) || ((data.message_kind === undefined) && (missing0 = "message_kind"))) || ((data.persona_id === undefined) && (missing0 = "persona_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.trace_display_mode === undefined) && (missing0 = "trace_display_mode"))) || ((data.allow_trace_collapse === undefined) && (missing0 = "allow_trace_collapse"))) || ((data.trace_summary === undefined) && (missing0 = "trace_summary"))) || ((data.trace_available === undefined) && (missing0 = "trace_available"))) || ((data.run_state === undefined) && (missing0 = "run_state"))) || ((data.reply_to === undefined) && (missing0 = "reply_to"))) || ((data.label === undefined) && (missing0 = "label"))) || ((data.payload === undefined) && (missing0 = "payload"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.allow_trace_collapse !== undefined){
const _errs1 = errors;
if(typeof data.allow_trace_collapse !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/allow_trace_collapse",schemaPath:"#/properties/allow_trace_collapse/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.attachments !== undefined){
let data1 = data.attachments;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(errors === _errs5){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
let data2 = data1[i0];
const _errs7 = errors;
if(errors === _errs7){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
const err0 = {instancePath:instancePath+"/attachments/" + i0,schemaPath:"#/properties/attachments/anyOf/0/items/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
var valid2 = _errs7 === errors;
if(!valid2){
break;
}
}
}
else {
const err1 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
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
const _errs10 = errors;
if(data1 !== null){
const err2 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate53.errors = vErrors;
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
if(data.content !== undefined){
const _errs12 = errors;
if(typeof data.content !== "string"){
validate53.errors = [{instancePath:instancePath+"/content",schemaPath:"#/properties/content/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
const _errs14 = errors;
if(typeof data.kind !== "string"){
validate53.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
let data5 = data.label;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(errors === _errs18){
if(data5 && typeof data5 == "object" && !Array.isArray(data5)){
}
else {
const err4 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
}
var _valid1 = _errs18 === errors;
valid3 = valid3 || _valid1;
const _errs21 = errors;
if(data5 !== null){
const err5 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid1 = _errs21 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err6 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
validate53.errors = vErrors;
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
if(data.message_id !== undefined){
let data6 = data.message_id;
const _errs23 = errors;
const _errs24 = errors;
let valid4 = false;
const _errs25 = errors;
if(typeof data6 !== "string"){
const err7 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs25 === errors;
valid4 = valid4 || _valid2;
const _errs27 = errors;
if(data6 !== null){
const err8 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var _valid2 = _errs27 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err9 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs24;
if(vErrors !== null){
if(_errs24){
vErrors.length = _errs24;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_kind !== undefined){
let data7 = data.message_kind;
const _errs29 = errors;
const _errs30 = errors;
let valid5 = false;
const _errs31 = errors;
if(typeof data7 !== "string"){
const err10 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs31 === errors;
valid5 = valid5 || _valid3;
const _errs33 = errors;
if(data7 !== null){
const err11 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid3 = _errs33 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err12 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs30;
if(vErrors !== null){
if(_errs30){
vErrors.length = _errs30;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data8 = data.payload;
const _errs35 = errors;
const _errs36 = errors;
let valid6 = false;
const _errs37 = errors;
if(errors === _errs37){
if(data8 && typeof data8 == "object" && !Array.isArray(data8)){
}
else {
const err13 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
}
var _valid4 = _errs37 === errors;
valid6 = valid6 || _valid4;
const _errs40 = errors;
if(data8 !== null){
const err14 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err15 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate53.errors = vErrors;
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
if(data.persona_id !== undefined){
let data9 = data.persona_id;
const _errs42 = errors;
const _errs43 = errors;
let valid7 = false;
const _errs44 = errors;
if(typeof data9 !== "string"){
const err16 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs44 === errors;
valid7 = valid7 || _valid5;
const _errs46 = errors;
if(data9 !== null){
const err17 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs46 === errors;
valid7 = valid7 || _valid5;
if(!valid7){
const err18 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate53.errors = vErrors;
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
if(valid0){
if(data.reply_to !== undefined){
let data10 = data.reply_to;
const _errs48 = errors;
const _errs49 = errors;
let valid8 = false;
const _errs50 = errors;
if(errors === _errs50){
if(data10 && typeof data10 == "object" && !Array.isArray(data10)){
}
else {
const err19 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
}
var _valid6 = _errs50 === errors;
valid8 = valid8 || _valid6;
const _errs53 = errors;
if(data10 !== null){
const err20 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid6 = _errs53 === errors;
valid8 = valid8 || _valid6;
if(!valid8){
const err21 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs49;
if(vErrors !== null){
if(_errs49){
vErrors.length = _errs49;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.role !== undefined){
const _errs55 = errors;
if(typeof data.role !== "string"){
validate53.errors = [{instancePath:instancePath+"/role",schemaPath:"#/properties/role/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs55 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.run_state !== undefined){
let data12 = data.run_state;
const _errs57 = errors;
const _errs58 = errors;
let valid9 = false;
const _errs59 = errors;
if(errors === _errs59){
if(data12 && typeof data12 == "object" && !Array.isArray(data12)){
}
else {
const err22 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
}
}
var _valid7 = _errs59 === errors;
valid9 = valid9 || _valid7;
const _errs62 = errors;
if(data12 !== null){
const err23 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
var _valid7 = _errs62 === errors;
valid9 = valid9 || _valid7;
if(!valid9){
const err24 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs58;
if(vErrors !== null){
if(_errs58){
vErrors.length = _errs58;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs57 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
let data13 = data.timestamp;
const _errs64 = errors;
if(!((typeof data13 == "number") && (!(data13 % 1) && !isNaN(data13)))){
validate53.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs64 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_available !== undefined){
const _errs66 = errors;
if(typeof data.trace_available !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/trace_available",schemaPath:"#/properties/trace_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs66 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_display_mode !== undefined){
let data15 = data.trace_display_mode;
const _errs68 = errors;
const _errs69 = errors;
let valid10 = false;
const _errs70 = errors;
if(typeof data15 !== "string"){
const err25 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err25];
}
else {
vErrors.push(err25);
}
errors++;
}
var _valid8 = _errs70 === errors;
valid10 = valid10 || _valid8;
const _errs72 = errors;
if(data15 !== null){
const err26 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err26];
}
else {
vErrors.push(err26);
}
errors++;
}
var _valid8 = _errs72 === errors;
valid10 = valid10 || _valid8;
if(!valid10){
const err27 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err27];
}
else {
vErrors.push(err27);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs69;
if(vErrors !== null){
if(_errs69){
vErrors.length = _errs69;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs68 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_summary !== undefined){
let data16 = data.trace_summary;
const _errs74 = errors;
const _errs75 = errors;
let valid11 = false;
const _errs76 = errors;
if(errors === _errs76){
if(data16 && typeof data16 == "object" && !Array.isArray(data16)){
}
else {
const err28 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err28];
}
else {
vErrors.push(err28);
}
errors++;
}
}
var _valid9 = _errs76 === errors;
valid11 = valid11 || _valid9;
const _errs79 = errors;
if(data16 !== null){
const err29 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err29];
}
else {
vErrors.push(err29);
}
errors++;
}
var _valid9 = _errs79 === errors;
valid11 = valid11 || _valid9;
if(!valid11){
const err30 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err30];
}
else {
vErrors.push(err30);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs75;
if(vErrors !== null){
if(_errs75){
vErrors.length = _errs75;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs74 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
let data17 = data.turn_id;
const _errs81 = errors;
const _errs82 = errors;
let valid12 = false;
const _errs83 = errors;
if(typeof data17 !== "string"){
const err31 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err31];
}
else {
vErrors.push(err31);
}
errors++;
}
var _valid10 = _errs83 === errors;
valid12 = valid12 || _valid10;
const _errs85 = errors;
if(data17 !== null){
const err32 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err32];
}
else {
vErrors.push(err32);
}
errors++;
}
var _valid10 = _errs85 === errors;
valid12 = valid12 || _valid10;
if(!valid12){
const err33 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err33];
}
else {
vErrors.push(err33);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs82;
if(vErrors !== null){
if(_errs82){
vErrors.length = _errs82;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs81 === errors;
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
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"allow_trace_collapse":true,"attachments":true,"content":true,"kind":true,"label":true,"message_id":true,"message_kind":true,"payload":true,"persona_id":true,"reply_to":true,"role":true,"run_state":true,"timestamp":true,"trace_available":true,"trace_display_mode":true,"trace_summary":true,"turn_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateChatSessionSummary = validate54;
const schema21 = {"description":"Typed session summary returned by the chat read model.","properties":{"history_version":{"default":0,"title":"History Version","type":"integer"},"last_message_preview":{"title":"Last Message Preview","type":"string"},"last_timestamp":{"title":"Last Timestamp","type":"integer"},"last_user_message_preview":{"title":"Last User Message Preview","type":"string"},"message_count":{"title":"Message Count","type":"integer"},"session_id":{"title":"Session Id","type":"string"},"title":{"title":"Title","type":"string"},"title_overridden":{"title":"Title Overridden","type":"boolean"},"workspace_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Workspace Path"}},"required":["session_id","title","last_message_preview","last_user_message_preview","title_overridden","last_timestamp","message_count","workspace_path","history_version"],"title":"ChatSessionSummary","type":"object"};

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
if((((((((((data.session_id === undefined) && (missing0 = "session_id")) || ((data.title === undefined) && (missing0 = "title"))) || ((data.last_message_preview === undefined) && (missing0 = "last_message_preview"))) || ((data.last_user_message_preview === undefined) && (missing0 = "last_user_message_preview"))) || ((data.title_overridden === undefined) && (missing0 = "title_overridden"))) || ((data.last_timestamp === undefined) && (missing0 = "last_timestamp"))) || ((data.message_count === undefined) && (missing0 = "message_count"))) || ((data.workspace_path === undefined) && (missing0 = "workspace_path"))) || ((data.history_version === undefined) && (missing0 = "history_version"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.history_version !== undefined){
let data0 = data.history_version;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate54.errors = [{instancePath:instancePath+"/history_version",schemaPath:"#/properties/history_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_message_preview !== undefined){
const _errs3 = errors;
if(typeof data.last_message_preview !== "string"){
validate54.errors = [{instancePath:instancePath+"/last_message_preview",schemaPath:"#/properties/last_message_preview/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_timestamp !== undefined){
let data2 = data.last_timestamp;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate54.errors = [{instancePath:instancePath+"/last_timestamp",schemaPath:"#/properties/last_timestamp/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_user_message_preview !== undefined){
const _errs7 = errors;
if(typeof data.last_user_message_preview !== "string"){
validate54.errors = [{instancePath:instancePath+"/last_user_message_preview",schemaPath:"#/properties/last_user_message_preview/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_count !== undefined){
let data4 = data.message_count;
const _errs9 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate54.errors = [{instancePath:instancePath+"/message_count",schemaPath:"#/properties/message_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs11 = errors;
if(typeof data.session_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs13 = errors;
if(typeof data.title !== "string"){
validate54.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title_overridden !== undefined){
const _errs15 = errors;
if(typeof data.title_overridden !== "boolean"){
validate54.errors = [{instancePath:instancePath+"/title_overridden",schemaPath:"#/properties/title_overridden/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.workspace_path !== undefined){
let data8 = data.workspace_path;
const _errs17 = errors;
const _errs18 = errors;
let valid1 = false;
const _errs19 = errors;
if(typeof data8 !== "string"){
const err0 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs19 === errors;
valid1 = valid1 || _valid0;
const _errs21 = errors;
if(data8 !== null){
const err1 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs21 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"history_version":true,"last_message_preview":true,"last_timestamp":true,"last_user_message_preview":true,"message_count":true,"session_id":true,"title":true,"title_overridden":true,"workspace_path":true},"dynamicProps":false,"dynamicItems":false};

export const validateBackgroundTask = validate55;
const schema22 = {"description":"Mutable runtime state for one background task.\n\n``task_id`` is stable across retries; each retry bumps ``attempt_index``\nand clears ``started_at`` / ``finished_at`` / ``error`` / ``summary`` /\n``result_payload`` before transitioning back to\n``pending``.","properties":{"attempt_index":{"default":0,"title":"Attempt Index","type":"integer"},"cancel_reason":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Cancel Reason"},"created_at":{"title":"Created At","type":"number"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"finished_at":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Finished At"},"result_payload":{"additionalProperties":true,"title":"Result Payload","type":"object"},"spec":{"$ref":"#/components/schemas/BackgroundTaskSpec"},"started_at":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Started At"},"status":{"$ref":"#/components/schemas/BackgroundTaskStatus","default":"pending"},"summary":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Summary"},"task_id":{"title":"Task Id","type":"string"},"updated_at":{"title":"Updated At","type":"number"},"user_task_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"User Task Id"}},"required":["task_id","spec","status","attempt_index","user_task_id","summary","result_payload","error","cancel_reason","created_at","started_at","finished_at","updated_at"],"title":"BackgroundTask","type":"object"};
const schema23 = {"description":"Immutable input used to (re-)launch a background task.\n\nA spec is created once at dispatch time and is preserved verbatim across\nretries; the mutable state lives on :class:`BackgroundTask`.","properties":{"agent_run_checkpoint":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Agent Run Checkpoint"},"context_sources":{"default":[],"items":{"additionalProperties":true,"type":"object"},"title":"Context Sources","type":"array"},"ephemeral_context":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Ephemeral Context"},"execution_preset":{"default":"background","title":"Execution Preset","type":"string"},"final_response_json_mode":{"default":false,"title":"Final Response Json Mode","type":"boolean"},"goal":{"title":"Goal","type":"string"},"max_iterations":{"default":50,"title":"Max Iterations","type":"integer"},"origin_turn_id":{"title":"Origin Turn Id","type":"string"},"parent_run_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Parent Run Id"},"pending_message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Pending Message Id"},"priority":{"default":0,"title":"Priority","type":"integer"},"reasoning_policy":{"additionalProperties":true,"title":"Reasoning Policy","type":"object"},"run_id":{"title":"Run Id","type":"string"},"selected_tools":{"items":{"type":"string"},"title":"Selected Tools","type":"array"},"session_id":{"title":"Session Id","type":"string"},"skill_preapproval_rules":{"default":[],"items":{"type":"string"},"title":"Skill Preapproval Rules","type":"array"},"system_prompt":{"default":"","title":"System Prompt","type":"string"},"task_budget_root_turn_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Task Budget Root Turn Id"},"timeout_seconds":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":1800,"title":"Timeout Seconds"},"title":{"title":"Title","type":"string"},"trigger":{"anyOf":[{"$ref":"#/components/schemas/RunTrigger"},{"type":"null"}],"default":null},"trigger_source":{"$ref":"#/components/schemas/BackgroundTaskTriggerSource","default":"rule"},"user_id":{"title":"User Id","type":"string"},"working_context":{"default":"","title":"Working Context","type":"string"},"workspace_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Workspace Path"}},"required":["user_id","session_id","origin_turn_id","title","goal","run_id","selected_tools","skill_preapproval_rules","system_prompt","working_context","ephemeral_context","execution_preset","reasoning_policy","parent_run_id","final_response_json_mode","context_sources","workspace_path","trigger_source","trigger","priority","max_iterations","timeout_seconds","task_budget_root_turn_id","agent_run_checkpoint","pending_message_id"],"title":"BackgroundTaskSpec","type":"object"};
const schema24 = {"description":"Describes how / why a run was started.\n\nCarried on ``AgentRun.trigger`` so observability, delivery, and retract\npropagation can preserve provenance.","properties":{"correlation":{"items":{"type":"string"},"title":"Correlation","type":"array"},"payload":{"additionalProperties":true,"title":"Payload","type":"object"},"priority":{"title":"Priority","type":"string"},"requester":{"title":"Requester","type":"string"},"source_channel":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Source Channel"},"trigger_type":{"title":"Trigger Type","type":"string"}},"required":["trigger_type","source_channel","requester","priority","correlation","payload"],"title":"RunTrigger","type":"object"};

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
if(((((((data.trigger_type === undefined) && (missing0 = "trigger_type")) || ((data.source_channel === undefined) && (missing0 = "source_channel"))) || ((data.requester === undefined) && (missing0 = "requester"))) || ((data.priority === undefined) && (missing0 = "priority"))) || ((data.correlation === undefined) && (missing0 = "correlation"))) || ((data.payload === undefined) && (missing0 = "payload"))){
validate57.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.correlation !== undefined){
let data0 = data.correlation;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(typeof data0[i0] !== "string"){
validate57.errors = [{instancePath:instancePath+"/correlation/" + i0,schemaPath:"#/properties/correlation/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate57.errors = [{instancePath:instancePath+"/correlation",schemaPath:"#/properties/correlation/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data2 = data.payload;
const _errs5 = errors;
if(errors === _errs5){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
validate57.errors = [{instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.priority !== undefined){
const _errs8 = errors;
if(typeof data.priority !== "string"){
validate57.errors = [{instancePath:instancePath+"/priority",schemaPath:"#/properties/priority/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.requester !== undefined){
const _errs10 = errors;
if(typeof data.requester !== "string"){
validate57.errors = [{instancePath:instancePath+"/requester",schemaPath:"#/properties/requester/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_channel !== undefined){
let data5 = data.source_channel;
const _errs12 = errors;
const _errs13 = errors;
let valid2 = false;
const _errs14 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/source_channel",schemaPath:"#/properties/source_channel/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs14 === errors;
valid2 = valid2 || _valid0;
const _errs16 = errors;
if(data5 !== null){
const err1 = {instancePath:instancePath+"/source_channel",schemaPath:"#/properties/source_channel/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs16 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err2 = {instancePath:instancePath+"/source_channel",schemaPath:"#/properties/source_channel/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.trigger_type !== undefined){
const _errs18 = errors;
if(typeof data.trigger_type !== "string"){
validate57.errors = [{instancePath:instancePath+"/trigger_type",schemaPath:"#/properties/trigger_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate57.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate57.errors = vErrors;
return errors === 0;
}
validate57.evaluated = {"props":{"correlation":true,"payload":true,"priority":true,"requester":true,"source_channel":true,"trigger_type":true},"dynamicProps":false,"dynamicItems":false};

const schema25 = {"description":"How a task was launched. Used for auditing and dispatcher metrics.","enum":["planner","classifier","user","manual","rule","schedule"],"title":"BackgroundTaskTriggerSource","type":"string"};

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
if(typeof data !== "string"){
validate59.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((data === "planner") || (data === "classifier")) || (data === "user")) || (data === "manual")) || (data === "rule")) || (data === "schedule"))){
validate59.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema25.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate59.errors = vErrors;
return errors === 0;
}
validate59.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if((((((((((((((((((((((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.origin_turn_id === undefined) && (missing0 = "origin_turn_id"))) || ((data.title === undefined) && (missing0 = "title"))) || ((data.goal === undefined) && (missing0 = "goal"))) || ((data.run_id === undefined) && (missing0 = "run_id"))) || ((data.selected_tools === undefined) && (missing0 = "selected_tools"))) || ((data.skill_preapproval_rules === undefined) && (missing0 = "skill_preapproval_rules"))) || ((data.system_prompt === undefined) && (missing0 = "system_prompt"))) || ((data.working_context === undefined) && (missing0 = "working_context"))) || ((data.ephemeral_context === undefined) && (missing0 = "ephemeral_context"))) || ((data.execution_preset === undefined) && (missing0 = "execution_preset"))) || ((data.reasoning_policy === undefined) && (missing0 = "reasoning_policy"))) || ((data.parent_run_id === undefined) && (missing0 = "parent_run_id"))) || ((data.final_response_json_mode === undefined) && (missing0 = "final_response_json_mode"))) || ((data.context_sources === undefined) && (missing0 = "context_sources"))) || ((data.workspace_path === undefined) && (missing0 = "workspace_path"))) || ((data.trigger_source === undefined) && (missing0 = "trigger_source"))) || ((data.trigger === undefined) && (missing0 = "trigger"))) || ((data.priority === undefined) && (missing0 = "priority"))) || ((data.max_iterations === undefined) && (missing0 = "max_iterations"))) || ((data.timeout_seconds === undefined) && (missing0 = "timeout_seconds"))) || ((data.task_budget_root_turn_id === undefined) && (missing0 = "task_budget_root_turn_id"))) || ((data.agent_run_checkpoint === undefined) && (missing0 = "agent_run_checkpoint"))) || ((data.pending_message_id === undefined) && (missing0 = "pending_message_id"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.agent_run_checkpoint !== undefined){
let data0 = data.agent_run_checkpoint;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(errors === _errs3){
if(data0 && typeof data0 == "object" && !Array.isArray(data0)){
}
else {
const err0 = {instancePath:instancePath+"/agent_run_checkpoint",schemaPath:"#/properties/agent_run_checkpoint/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs6 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/agent_run_checkpoint",schemaPath:"#/properties/agent_run_checkpoint/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/agent_run_checkpoint",schemaPath:"#/properties/agent_run_checkpoint/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.context_sources !== undefined){
let data1 = data.context_sources;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
let data2 = data1[i0];
const _errs10 = errors;
if(errors === _errs10){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
validate56.errors = [{instancePath:instancePath+"/context_sources/" + i0,schemaPath:"#/properties/context_sources/items/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/context_sources",schemaPath:"#/properties/context_sources/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ephemeral_context !== undefined){
let data3 = data.ephemeral_context;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(typeof data3 !== "string"){
const err3 = {instancePath:instancePath+"/ephemeral_context",schemaPath:"#/properties/ephemeral_context/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid3 = valid3 || _valid1;
const _errs17 = errors;
if(data3 !== null){
const err4 = {instancePath:instancePath+"/ephemeral_context",schemaPath:"#/properties/ephemeral_context/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/ephemeral_context",schemaPath:"#/properties/ephemeral_context/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.execution_preset !== undefined){
const _errs19 = errors;
if(typeof data.execution_preset !== "string"){
validate56.errors = [{instancePath:instancePath+"/execution_preset",schemaPath:"#/properties/execution_preset/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.final_response_json_mode !== undefined){
const _errs21 = errors;
if(typeof data.final_response_json_mode !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/final_response_json_mode",schemaPath:"#/properties/final_response_json_mode/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.goal !== undefined){
const _errs23 = errors;
if(typeof data.goal !== "string"){
validate56.errors = [{instancePath:instancePath+"/goal",schemaPath:"#/properties/goal/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_iterations !== undefined){
let data7 = data.max_iterations;
const _errs25 = errors;
if(!((typeof data7 == "number") && (!(data7 % 1) && !isNaN(data7)))){
validate56.errors = [{instancePath:instancePath+"/max_iterations",schemaPath:"#/properties/max_iterations/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.origin_turn_id !== undefined){
const _errs27 = errors;
if(typeof data.origin_turn_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/origin_turn_id",schemaPath:"#/properties/origin_turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.parent_run_id !== undefined){
let data9 = data.parent_run_id;
const _errs29 = errors;
const _errs30 = errors;
let valid4 = false;
const _errs31 = errors;
if(typeof data9 !== "string"){
const err6 = {instancePath:instancePath+"/parent_run_id",schemaPath:"#/properties/parent_run_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs31 === errors;
valid4 = valid4 || _valid2;
const _errs33 = errors;
if(data9 !== null){
const err7 = {instancePath:instancePath+"/parent_run_id",schemaPath:"#/properties/parent_run_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs33 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/parent_run_id",schemaPath:"#/properties/parent_run_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
errors = _errs30;
if(vErrors !== null){
if(_errs30){
vErrors.length = _errs30;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.pending_message_id !== undefined){
let data10 = data.pending_message_id;
const _errs35 = errors;
const _errs36 = errors;
let valid5 = false;
const _errs37 = errors;
if(typeof data10 !== "string"){
const err9 = {instancePath:instancePath+"/pending_message_id",schemaPath:"#/properties/pending_message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs37 === errors;
valid5 = valid5 || _valid3;
const _errs39 = errors;
if(data10 !== null){
const err10 = {instancePath:instancePath+"/pending_message_id",schemaPath:"#/properties/pending_message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs39 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err11 = {instancePath:instancePath+"/pending_message_id",schemaPath:"#/properties/pending_message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate56.errors = vErrors;
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
if(data.priority !== undefined){
let data11 = data.priority;
const _errs41 = errors;
if(!((typeof data11 == "number") && (!(data11 % 1) && !isNaN(data11)))){
validate56.errors = [{instancePath:instancePath+"/priority",schemaPath:"#/properties/priority/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reasoning_policy !== undefined){
let data12 = data.reasoning_policy;
const _errs43 = errors;
if(errors === _errs43){
if(data12 && typeof data12 == "object" && !Array.isArray(data12)){
}
else {
validate56.errors = [{instancePath:instancePath+"/reasoning_policy",schemaPath:"#/properties/reasoning_policy/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.run_id !== undefined){
const _errs46 = errors;
if(typeof data.run_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs46 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.selected_tools !== undefined){
let data14 = data.selected_tools;
const _errs48 = errors;
if(errors === _errs48){
if(Array.isArray(data14)){
var valid6 = true;
const len1 = data14.length;
for(let i1=0; i1<len1; i1++){
const _errs50 = errors;
if(typeof data14[i1] !== "string"){
validate56.errors = [{instancePath:instancePath+"/selected_tools/" + i1,schemaPath:"#/properties/selected_tools/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid6 = _errs50 === errors;
if(!valid6){
break;
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/selected_tools",schemaPath:"#/properties/selected_tools/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs52 = errors;
if(typeof data.session_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs52 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.skill_preapproval_rules !== undefined){
let data17 = data.skill_preapproval_rules;
const _errs54 = errors;
if(errors === _errs54){
if(Array.isArray(data17)){
var valid7 = true;
const len2 = data17.length;
for(let i2=0; i2<len2; i2++){
const _errs56 = errors;
if(typeof data17[i2] !== "string"){
validate56.errors = [{instancePath:instancePath+"/skill_preapproval_rules/" + i2,schemaPath:"#/properties/skill_preapproval_rules/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid7 = _errs56 === errors;
if(!valid7){
break;
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/skill_preapproval_rules",schemaPath:"#/properties/skill_preapproval_rules/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs54 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.system_prompt !== undefined){
const _errs58 = errors;
if(typeof data.system_prompt !== "string"){
validate56.errors = [{instancePath:instancePath+"/system_prompt",schemaPath:"#/properties/system_prompt/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs58 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.task_budget_root_turn_id !== undefined){
let data20 = data.task_budget_root_turn_id;
const _errs60 = errors;
const _errs61 = errors;
let valid8 = false;
const _errs62 = errors;
if(typeof data20 !== "string"){
const err12 = {instancePath:instancePath+"/task_budget_root_turn_id",schemaPath:"#/properties/task_budget_root_turn_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs62 === errors;
valid8 = valid8 || _valid4;
const _errs64 = errors;
if(data20 !== null){
const err13 = {instancePath:instancePath+"/task_budget_root_turn_id",schemaPath:"#/properties/task_budget_root_turn_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs64 === errors;
valid8 = valid8 || _valid4;
if(!valid8){
const err14 = {instancePath:instancePath+"/task_budget_root_turn_id",schemaPath:"#/properties/task_budget_root_turn_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs61;
if(vErrors !== null){
if(_errs61){
vErrors.length = _errs61;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs60 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timeout_seconds !== undefined){
let data21 = data.timeout_seconds;
const _errs66 = errors;
const _errs67 = errors;
let valid9 = false;
const _errs68 = errors;
if(!((typeof data21 == "number") && (!(data21 % 1) && !isNaN(data21)))){
const err15 = {instancePath:instancePath+"/timeout_seconds",schemaPath:"#/properties/timeout_seconds/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var _valid5 = _errs68 === errors;
valid9 = valid9 || _valid5;
const _errs70 = errors;
if(data21 !== null){
const err16 = {instancePath:instancePath+"/timeout_seconds",schemaPath:"#/properties/timeout_seconds/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs70 === errors;
valid9 = valid9 || _valid5;
if(!valid9){
const err17 = {instancePath:instancePath+"/timeout_seconds",schemaPath:"#/properties/timeout_seconds/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs67;
if(vErrors !== null){
if(_errs67){
vErrors.length = _errs67;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs66 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs72 = errors;
if(typeof data.title !== "string"){
validate56.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs72 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trigger !== undefined){
let data23 = data.trigger;
const _errs74 = errors;
const _errs75 = errors;
let valid10 = false;
const _errs76 = errors;
if(!(validate57(data23, {instancePath:instancePath+"/trigger",parentData:data,parentDataProperty:"trigger",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var _valid6 = _errs76 === errors;
valid10 = valid10 || _valid6;
if(_valid6){
var props1 = {};
props1.correlation = true;
props1.payload = true;
props1.priority = true;
props1.requester = true;
props1.source_channel = true;
props1.trigger_type = true;
}
const _errs77 = errors;
if(data23 !== null){
const err18 = {instancePath:instancePath+"/trigger",schemaPath:"#/properties/trigger/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
}
var _valid6 = _errs77 === errors;
valid10 = valid10 || _valid6;
if(!valid10){
const err19 = {instancePath:instancePath+"/trigger",schemaPath:"#/properties/trigger/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs75;
if(vErrors !== null){
if(_errs75){
vErrors.length = _errs75;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs74 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trigger_source !== undefined){
const _errs79 = errors;
if(!(validate59(data.trigger_source, {instancePath:instancePath+"/trigger_source",parentData:data,parentDataProperty:"trigger_source",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate59.errors : vErrors.concat(validate59.errors);
errors = vErrors.length;
}
var valid0 = _errs79 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs80 = errors;
if(typeof data.user_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs80 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.working_context !== undefined){
const _errs82 = errors;
if(typeof data.working_context !== "string"){
validate56.errors = [{instancePath:instancePath+"/working_context",schemaPath:"#/properties/working_context/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs82 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.workspace_path !== undefined){
let data27 = data.workspace_path;
const _errs84 = errors;
const _errs85 = errors;
let valid11 = false;
const _errs86 = errors;
if(typeof data27 !== "string"){
const err20 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid7 = _errs86 === errors;
valid11 = valid11 || _valid7;
const _errs88 = errors;
if(data27 !== null){
const err21 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
}
var _valid7 = _errs88 === errors;
valid11 = valid11 || _valid7;
if(!valid11){
const err22 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs85;
if(vErrors !== null){
if(_errs85){
vErrors.length = _errs85;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs84 === errors;
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
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"agent_run_checkpoint":true,"context_sources":true,"ephemeral_context":true,"execution_preset":true,"final_response_json_mode":true,"goal":true,"max_iterations":true,"origin_turn_id":true,"parent_run_id":true,"pending_message_id":true,"priority":true,"reasoning_policy":true,"run_id":true,"selected_tools":true,"session_id":true,"skill_preapproval_rules":true,"system_prompt":true,"task_budget_root_turn_id":true,"timeout_seconds":true,"title":true,"trigger":true,"trigger_source":true,"user_id":true,"working_context":true,"workspace_path":true},"dynamicProps":false,"dynamicItems":false};

const schema26 = {"description":"Lifecycle states for a background task.\n\nThe valid transitions are:\n\n* ``pending`` → ``running`` (slot acquired) | ``cancelled``\n* ``running`` → ``cancelling`` | ``succeeded`` | ``failed``\n  | ``suspended_waiting_user``\n* ``suspended_waiting_user`` → ``running`` (user answered the prompt)\n  | ``cancelling``\n* ``cancelling`` → ``cancelled``\n* ``failed`` / ``cancelled`` → ``pending`` on retry (new ``attempt_index``)\n\nSucceeded tasks are terminal.","enum":["pending","running","cancelling","cancelled","succeeded","failed","suspended_waiting_user"],"title":"BackgroundTaskStatus","type":"string"};

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
if(typeof data !== "string"){
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data === "pending") || (data === "running")) || (data === "cancelling")) || (data === "cancelled")) || (data === "succeeded")) || (data === "failed")) || (data === "suspended_waiting_user"))){
validate62.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema26.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if((((((((((((((data.task_id === undefined) && (missing0 = "task_id")) || ((data.spec === undefined) && (missing0 = "spec"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.attempt_index === undefined) && (missing0 = "attempt_index"))) || ((data.user_task_id === undefined) && (missing0 = "user_task_id"))) || ((data.summary === undefined) && (missing0 = "summary"))) || ((data.result_payload === undefined) && (missing0 = "result_payload"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.cancel_reason === undefined) && (missing0 = "cancel_reason"))) || ((data.created_at === undefined) && (missing0 = "created_at"))) || ((data.started_at === undefined) && (missing0 = "started_at"))) || ((data.finished_at === undefined) && (missing0 = "finished_at"))) || ((data.updated_at === undefined) && (missing0 = "updated_at"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.attempt_index !== undefined){
let data0 = data.attempt_index;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate55.errors = [{instancePath:instancePath+"/attempt_index",schemaPath:"#/properties/attempt_index/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cancel_reason !== undefined){
let data1 = data.cancel_reason;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/cancel_reason",schemaPath:"#/properties/cancel_reason/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/cancel_reason",schemaPath:"#/properties/cancel_reason/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/cancel_reason",schemaPath:"#/properties/cancel_reason/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.created_at !== undefined){
const _errs9 = errors;
if(!(typeof data.created_at == "number")){
validate55.errors = [{instancePath:instancePath+"/created_at",schemaPath:"#/properties/created_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data3 = data.error;
const _errs11 = errors;
const _errs12 = errors;
let valid2 = false;
const _errs13 = errors;
if(typeof data3 !== "string"){
const err3 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs13 === errors;
valid2 = valid2 || _valid1;
const _errs15 = errors;
if(data3 !== null){
const err4 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.finished_at !== undefined){
let data4 = data.finished_at;
const _errs17 = errors;
const _errs18 = errors;
let valid3 = false;
const _errs19 = errors;
if(!(typeof data4 == "number")){
const err6 = {instancePath:instancePath+"/finished_at",schemaPath:"#/properties/finished_at/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
const _errs21 = errors;
if(data4 !== null){
const err7 = {instancePath:instancePath+"/finished_at",schemaPath:"#/properties/finished_at/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/finished_at",schemaPath:"#/properties/finished_at/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.result_payload !== undefined){
let data5 = data.result_payload;
const _errs23 = errors;
if(errors === _errs23){
if(data5 && typeof data5 == "object" && !Array.isArray(data5)){
}
else {
validate55.errors = [{instancePath:instancePath+"/result_payload",schemaPath:"#/properties/result_payload/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.spec !== undefined){
const _errs26 = errors;
if(!(validate56(data.spec, {instancePath:instancePath+"/spec",parentData:data,parentDataProperty:"spec",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.started_at !== undefined){
let data7 = data.started_at;
const _errs27 = errors;
const _errs28 = errors;
let valid4 = false;
const _errs29 = errors;
if(!(typeof data7 == "number")){
const err9 = {instancePath:instancePath+"/started_at",schemaPath:"#/properties/started_at/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs29 === errors;
valid4 = valid4 || _valid3;
const _errs31 = errors;
if(data7 !== null){
const err10 = {instancePath:instancePath+"/started_at",schemaPath:"#/properties/started_at/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs31 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/started_at",schemaPath:"#/properties/started_at/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
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
if(data.status !== undefined){
const _errs33 = errors;
if(!(validate62(data.status, {instancePath:instancePath+"/status",parentData:data,parentDataProperty:"status",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.summary !== undefined){
let data9 = data.summary;
const _errs34 = errors;
const _errs35 = errors;
let valid5 = false;
const _errs36 = errors;
if(typeof data9 !== "string"){
const err12 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs36 === errors;
valid5 = valid5 || _valid4;
const _errs38 = errors;
if(data9 !== null){
const err13 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs38 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err14 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs35;
if(vErrors !== null){
if(_errs35){
vErrors.length = _errs35;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.task_id !== undefined){
const _errs40 = errors;
if(typeof data.task_id !== "string"){
validate55.errors = [{instancePath:instancePath+"/task_id",schemaPath:"#/properties/task_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs40 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.updated_at !== undefined){
const _errs42 = errors;
if(!(typeof data.updated_at == "number")){
validate55.errors = [{instancePath:instancePath+"/updated_at",schemaPath:"#/properties/updated_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_task_id !== undefined){
let data12 = data.user_task_id;
const _errs44 = errors;
const _errs45 = errors;
let valid6 = false;
const _errs46 = errors;
if(typeof data12 !== "string"){
const err15 = {instancePath:instancePath+"/user_task_id",schemaPath:"#/properties/user_task_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var _valid5 = _errs46 === errors;
valid6 = valid6 || _valid5;
const _errs48 = errors;
if(data12 !== null){
const err16 = {instancePath:instancePath+"/user_task_id",schemaPath:"#/properties/user_task_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs48 === errors;
valid6 = valid6 || _valid5;
if(!valid6){
const err17 = {instancePath:instancePath+"/user_task_id",schemaPath:"#/properties/user_task_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
validate55.errors = vErrors;
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
validate55.evaluated = {"props":{"attempt_index":true,"cancel_reason":true,"created_at":true,"error":true,"finished_at":true,"result_payload":true,"spec":true,"started_at":true,"status":true,"summary":true,"task_id":true,"updated_at":true,"user_task_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateBackgroundTaskEvent = validate64;
const schema27 = {"description":"An append-only entry in the task's event log.\n\nEvents are recorded for every state transition plus ad-hoc progress\nnotes. The store guarantees insertion order but does not enforce any\ntransition validity; the manager is the authority on legal transitions.","properties":{"attempt_index":{"title":"Attempt Index","type":"integer"},"created_at":{"title":"Created At","type":"number"},"event_id":{"title":"Event Id","type":"string"},"event_type":{"title":"Event Type","type":"string"},"from_status":{"anyOf":[{"$ref":"#/components/schemas/BackgroundTaskStatus"},{"type":"null"}]},"message":{"default":"","title":"Message","type":"string"},"payload":{"additionalProperties":true,"title":"Payload","type":"object"},"task_id":{"title":"Task Id","type":"string"},"to_status":{"anyOf":[{"$ref":"#/components/schemas/BackgroundTaskStatus"},{"type":"null"}]}},"required":["event_id","task_id","attempt_index","event_type","from_status","to_status","message","payload","created_at"],"title":"BackgroundTaskEvent","type":"object"};

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
if((((((((((data.event_id === undefined) && (missing0 = "event_id")) || ((data.task_id === undefined) && (missing0 = "task_id"))) || ((data.attempt_index === undefined) && (missing0 = "attempt_index"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.from_status === undefined) && (missing0 = "from_status"))) || ((data.to_status === undefined) && (missing0 = "to_status"))) || ((data.message === undefined) && (missing0 = "message"))) || ((data.payload === undefined) && (missing0 = "payload"))) || ((data.created_at === undefined) && (missing0 = "created_at"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.attempt_index !== undefined){
let data0 = data.attempt_index;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate64.errors = [{instancePath:instancePath+"/attempt_index",schemaPath:"#/properties/attempt_index/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.created_at !== undefined){
const _errs3 = errors;
if(!(typeof data.created_at == "number")){
validate64.errors = [{instancePath:instancePath+"/created_at",schemaPath:"#/properties/created_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
const _errs5 = errors;
if(typeof data.event_id !== "string"){
validate64.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
const _errs7 = errors;
if(typeof data.event_type !== "string"){
validate64.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.from_status !== undefined){
let data4 = data.from_status;
const _errs9 = errors;
const _errs10 = errors;
let valid1 = false;
const _errs11 = errors;
if(!(validate62(data4, {instancePath:instancePath+"/from_status",parentData:data,parentDataProperty:"from_status",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var _valid0 = _errs11 === errors;
valid1 = valid1 || _valid0;
const _errs12 = errors;
if(data4 !== null){
const err0 = {instancePath:instancePath+"/from_status",schemaPath:"#/properties/from_status/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
if(!valid1){
const err1 = {instancePath:instancePath+"/from_status",schemaPath:"#/properties/from_status/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate64.errors = vErrors;
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
if(data.message !== undefined){
const _errs14 = errors;
if(typeof data.message !== "string"){
validate64.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data6 = data.payload;
const _errs16 = errors;
if(errors === _errs16){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
}
else {
validate64.errors = [{instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.task_id !== undefined){
const _errs19 = errors;
if(typeof data.task_id !== "string"){
validate64.errors = [{instancePath:instancePath+"/task_id",schemaPath:"#/properties/task_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.to_status !== undefined){
let data8 = data.to_status;
const _errs21 = errors;
const _errs22 = errors;
let valid2 = false;
const _errs23 = errors;
if(!(validate62(data8, {instancePath:instancePath+"/to_status",parentData:data,parentDataProperty:"to_status",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var _valid1 = _errs23 === errors;
valid2 = valid2 || _valid1;
const _errs24 = errors;
if(data8 !== null){
const err2 = {instancePath:instancePath+"/to_status",schemaPath:"#/properties/to_status/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs24 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err3 = {instancePath:instancePath+"/to_status",schemaPath:"#/properties/to_status/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate64.errors = vErrors;
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
validate64.evaluated = {"props":{"attempt_index":true,"created_at":true,"event_id":true,"event_type":true,"from_status":true,"message":true,"payload":true,"task_id":true,"to_status":true},"dynamicProps":false,"dynamicItems":false};

export const validateRunEvent = validate67;
const schema28 = {"additionalProperties":false,"properties":{"kind":{"enum":["stdout","stderr","tool_call","tool_result","assistant_text","thinking","status","error"],"title":"Kind","type":"string"},"payload":{"additionalProperties":true,"title":"Payload","type":"object"},"ts_ms":{"minimum":0,"title":"Ts Ms","type":"integer"}},"required":["kind","ts_ms","payload"],"title":"RunEvent","type":"object"};

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
if((((data.kind === undefined) && (missing0 = "kind")) || ((data.ts_ms === undefined) && (missing0 = "ts_ms"))) || ((data.payload === undefined) && (missing0 = "payload"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "kind") || (key0 === "payload")) || (key0 === "ts_ms"))){
validate67.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.kind !== undefined){
let data0 = data.kind;
const _errs2 = errors;
if(typeof data0 !== "string"){
validate67.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((((data0 === "stdout") || (data0 === "stderr")) || (data0 === "tool_call")) || (data0 === "tool_result")) || (data0 === "assistant_text")) || (data0 === "thinking")) || (data0 === "status")) || (data0 === "error"))){
validate67.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema28.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data1 = data.payload;
const _errs4 = errors;
if(errors === _errs4){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
}
else {
validate67.errors = [{instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ts_ms !== undefined){
let data2 = data.ts_ms;
const _errs7 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate67.errors = [{instancePath:instancePath+"/ts_ms",schemaPath:"#/properties/ts_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs7){
if(typeof data2 == "number"){
if(data2 < 0 || isNaN(data2)){
validate67.errors = [{instancePath:instancePath+"/ts_ms",schemaPath:"#/properties/ts_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
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
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateDelegateResult = validate68;
const schema29 = {"additionalProperties":false,"properties":{"adapter":{"maxLength":256,"minLength":1,"pattern":"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$","title":"Adapter","type":"string"},"applied":{"default":false,"title":"Applied","type":"boolean"},"applied_at":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Applied At"},"applied_files":{"items":{"type":"string"},"title":"Applied Files","type":"array"},"artifact_registered":{"default":false,"title":"Artifact Registered","type":"boolean"},"cancelled":{"default":false,"title":"Cancelled","type":"boolean"},"cost":{"anyOf":[{"$ref":"#/components/schemas/CostInfo"},{"type":"null"}]},"delegation_id":{"title":"Delegation Id","type":"string"},"diff_path":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Diff Path"},"diff_stats":{"$ref":"#/components/schemas/DiffStats"},"duration_ms":{"minimum":0,"title":"Duration Ms","type":"integer"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Error"},"events_path":{"title":"Events Path","type":"string"},"exit_code":{"title":"Exit Code","type":"integer"},"files_changed":{"items":{"type":"string"},"title":"Files Changed","type":"array"},"logs_path":{"title":"Logs Path","type":"string"},"success":{"title":"Success","type":"boolean"},"summary":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Summary"}},"required":["delegation_id","success","exit_code","duration_ms","adapter","diff_path","diff_stats","files_changed","summary","logs_path","events_path","error","cost","artifact_registered","applied","applied_at","applied_files","cancelled"],"title":"DelegateResult","type":"object"};
const func1 = Object.prototype.hasOwnProperty;
const func2 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });
const pattern3 = new RegExp("^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$", "u");
const schema30 = {"additionalProperties":false,"properties":{"input_tokens":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Input Tokens"},"output_tokens":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Output Tokens"},"usd":{"anyOf":[{"type":"number"},{"type":"null"}],"default":null,"title":"Usd"}},"required":["usd","input_tokens","output_tokens"],"title":"CostInfo","type":"object"};

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
if((((data.usd === undefined) && (missing0 = "usd")) || ((data.input_tokens === undefined) && (missing0 = "input_tokens"))) || ((data.output_tokens === undefined) && (missing0 = "output_tokens"))){
validate69.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "input_tokens") || (key0 === "output_tokens")) || (key0 === "usd"))){
validate69.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.input_tokens !== undefined){
let data0 = data.input_tokens;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
const err0 = {instancePath:instancePath+"/input_tokens",schemaPath:"#/properties/input_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
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
if(data0 < 0 || isNaN(data0)){
const err1 = {instancePath:instancePath+"/input_tokens",schemaPath:"#/properties/input_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
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
const err2 = {instancePath:instancePath+"/input_tokens",schemaPath:"#/properties/input_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err3 = {instancePath:instancePath+"/input_tokens",schemaPath:"#/properties/input_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate69.errors = vErrors;
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
if(data.output_tokens !== undefined){
let data1 = data.output_tokens;
const _errs8 = errors;
const _errs9 = errors;
let valid2 = false;
const _errs10 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
const err4 = {instancePath:instancePath+"/output_tokens",schemaPath:"#/properties/output_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
if(errors === _errs10){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
const err5 = {instancePath:instancePath+"/output_tokens",schemaPath:"#/properties/output_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
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
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
const _errs12 = errors;
if(data1 !== null){
const err6 = {instancePath:instancePath+"/output_tokens",schemaPath:"#/properties/output_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/output_tokens",schemaPath:"#/properties/output_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate69.errors = vErrors;
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
if(data.usd !== undefined){
let data2 = data.usd;
const _errs14 = errors;
const _errs15 = errors;
let valid3 = false;
const _errs16 = errors;
if(!(typeof data2 == "number")){
const err8 = {instancePath:instancePath+"/usd",schemaPath:"#/properties/usd/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var _valid2 = _errs16 === errors;
valid3 = valid3 || _valid2;
const _errs18 = errors;
if(data2 !== null){
const err9 = {instancePath:instancePath+"/usd",schemaPath:"#/properties/usd/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid2 = _errs18 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err10 = {instancePath:instancePath+"/usd",schemaPath:"#/properties/usd/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
validate69.errors = vErrors;
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
validate69.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema31 = {"additionalProperties":false,"properties":{"additions":{"default":0,"minimum":0,"title":"Additions","type":"integer"},"deletions":{"default":0,"minimum":0,"title":"Deletions","type":"integer"},"files_changed":{"default":0,"minimum":0,"title":"Files Changed","type":"integer"}},"required":["files_changed","additions","deletions"],"title":"DiffStats","type":"object"};

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
if((((data.files_changed === undefined) && (missing0 = "files_changed")) || ((data.additions === undefined) && (missing0 = "additions"))) || ((data.deletions === undefined) && (missing0 = "deletions"))){
validate71.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "additions") || (key0 === "deletions")) || (key0 === "files_changed"))){
validate71.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.additions !== undefined){
let data0 = data.additions;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate71.errors = [{instancePath:instancePath+"/additions",schemaPath:"#/properties/additions/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs2){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
validate71.errors = [{instancePath:instancePath+"/additions",schemaPath:"#/properties/additions/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
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
if(data.deletions !== undefined){
let data1 = data.deletions;
const _errs4 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate71.errors = [{instancePath:instancePath+"/deletions",schemaPath:"#/properties/deletions/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs4){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
validate71.errors = [{instancePath:instancePath+"/deletions",schemaPath:"#/properties/deletions/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
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
if(data.files_changed !== undefined){
let data2 = data.files_changed;
const _errs6 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate71.errors = [{instancePath:instancePath+"/files_changed",schemaPath:"#/properties/files_changed/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs6){
if(typeof data2 == "number"){
if(data2 < 0 || isNaN(data2)){
validate71.errors = [{instancePath:instancePath+"/files_changed",schemaPath:"#/properties/files_changed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
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
validate71.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate71.errors = vErrors;
return errors === 0;
}
validate71.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if(((((((((((((((((((data.delegation_id === undefined) && (missing0 = "delegation_id")) || ((data.success === undefined) && (missing0 = "success"))) || ((data.exit_code === undefined) && (missing0 = "exit_code"))) || ((data.duration_ms === undefined) && (missing0 = "duration_ms"))) || ((data.adapter === undefined) && (missing0 = "adapter"))) || ((data.diff_path === undefined) && (missing0 = "diff_path"))) || ((data.diff_stats === undefined) && (missing0 = "diff_stats"))) || ((data.files_changed === undefined) && (missing0 = "files_changed"))) || ((data.summary === undefined) && (missing0 = "summary"))) || ((data.logs_path === undefined) && (missing0 = "logs_path"))) || ((data.events_path === undefined) && (missing0 = "events_path"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.cost === undefined) && (missing0 = "cost"))) || ((data.artifact_registered === undefined) && (missing0 = "artifact_registered"))) || ((data.applied === undefined) && (missing0 = "applied"))) || ((data.applied_at === undefined) && (missing0 = "applied_at"))) || ((data.applied_files === undefined) && (missing0 = "applied_files"))) || ((data.cancelled === undefined) && (missing0 = "cancelled"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func1.call(schema29.properties, key0))){
validate68.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.adapter !== undefined){
let data0 = data.adapter;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func2(data0) > 256){
validate68.errors = [{instancePath:instancePath+"/adapter",schemaPath:"#/properties/adapter/maxLength",keyword:"maxLength",params:{limit: 256},message:"must NOT have more than 256 characters"}];
return false;
}
else {
if(func2(data0) < 1){
validate68.errors = [{instancePath:instancePath+"/adapter",schemaPath:"#/properties/adapter/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
else {
if(!pattern3.test(data0)){
validate68.errors = [{instancePath:instancePath+"/adapter",schemaPath:"#/properties/adapter/pattern",keyword:"pattern",params:{pattern: "^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"},message:"must match pattern \""+"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"+"\""}];
return false;
}
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/adapter",schemaPath:"#/properties/adapter/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.applied !== undefined){
const _errs4 = errors;
if(typeof data.applied !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/applied",schemaPath:"#/properties/applied/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.applied_at !== undefined){
let data2 = data.applied_at;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
const err0 = {instancePath:instancePath+"/applied_at",schemaPath:"#/properties/applied_at/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs8){
if(typeof data2 == "number"){
if(data2 < 0 || isNaN(data2)){
const err1 = {instancePath:instancePath+"/applied_at",schemaPath:"#/properties/applied_at/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
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
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data2 !== null){
const err2 = {instancePath:instancePath+"/applied_at",schemaPath:"#/properties/applied_at/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/applied_at",schemaPath:"#/properties/applied_at/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate68.errors = vErrors;
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
if(data.applied_files !== undefined){
let data3 = data.applied_files;
const _errs12 = errors;
if(errors === _errs12){
if(Array.isArray(data3)){
var valid2 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
const _errs14 = errors;
if(typeof data3[i0] !== "string"){
validate68.errors = [{instancePath:instancePath+"/applied_files/" + i0,schemaPath:"#/properties/applied_files/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs14 === errors;
if(!valid2){
break;
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/applied_files",schemaPath:"#/properties/applied_files/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.artifact_registered !== undefined){
const _errs16 = errors;
if(typeof data.artifact_registered !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/artifact_registered",schemaPath:"#/properties/artifact_registered/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cancelled !== undefined){
const _errs18 = errors;
if(typeof data.cancelled !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/cancelled",schemaPath:"#/properties/cancelled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cost !== undefined){
let data7 = data.cost;
const _errs20 = errors;
const _errs21 = errors;
let valid3 = false;
const _errs22 = errors;
if(!(validate69(data7, {instancePath:instancePath+"/cost",parentData:data,parentDataProperty:"cost",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate69.errors : vErrors.concat(validate69.errors);
errors = vErrors.length;
}
var _valid1 = _errs22 === errors;
valid3 = valid3 || _valid1;
const _errs23 = errors;
if(data7 !== null){
const err4 = {instancePath:instancePath+"/cost",schemaPath:"#/properties/cost/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs23 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/cost",schemaPath:"#/properties/cost/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate68.errors = vErrors;
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
if(data.delegation_id !== undefined){
const _errs25 = errors;
if(typeof data.delegation_id !== "string"){
validate68.errors = [{instancePath:instancePath+"/delegation_id",schemaPath:"#/properties/delegation_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.diff_path !== undefined){
let data9 = data.diff_path;
const _errs27 = errors;
const _errs28 = errors;
let valid4 = false;
const _errs29 = errors;
if(typeof data9 !== "string"){
const err6 = {instancePath:instancePath+"/diff_path",schemaPath:"#/properties/diff_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs29 === errors;
valid4 = valid4 || _valid2;
const _errs31 = errors;
if(data9 !== null){
const err7 = {instancePath:instancePath+"/diff_path",schemaPath:"#/properties/diff_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs31 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/diff_path",schemaPath:"#/properties/diff_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate68.errors = vErrors;
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
if(data.diff_stats !== undefined){
const _errs33 = errors;
if(!(validate71(data.diff_stats, {instancePath:instancePath+"/diff_stats",parentData:data,parentDataProperty:"diff_stats",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate71.errors : vErrors.concat(validate71.errors);
errors = vErrors.length;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.duration_ms !== undefined){
let data11 = data.duration_ms;
const _errs34 = errors;
if(!((typeof data11 == "number") && (!(data11 % 1) && !isNaN(data11)))){
validate68.errors = [{instancePath:instancePath+"/duration_ms",schemaPath:"#/properties/duration_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs34){
if(typeof data11 == "number"){
if(data11 < 0 || isNaN(data11)){
validate68.errors = [{instancePath:instancePath+"/duration_ms",schemaPath:"#/properties/duration_ms/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data12 = data.error;
const _errs36 = errors;
const _errs37 = errors;
let valid5 = false;
const _errs38 = errors;
if(typeof data12 !== "string"){
const err9 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const _errs40 = errors;
if(data12 !== null){
const err10 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs40 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err11 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate68.errors = vErrors;
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
if(data.events_path !== undefined){
const _errs42 = errors;
if(typeof data.events_path !== "string"){
validate68.errors = [{instancePath:instancePath+"/events_path",schemaPath:"#/properties/events_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.exit_code !== undefined){
let data14 = data.exit_code;
const _errs44 = errors;
if(!((typeof data14 == "number") && (!(data14 % 1) && !isNaN(data14)))){
validate68.errors = [{instancePath:instancePath+"/exit_code",schemaPath:"#/properties/exit_code/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.files_changed !== undefined){
let data15 = data.files_changed;
const _errs46 = errors;
if(errors === _errs46){
if(Array.isArray(data15)){
var valid6 = true;
const len1 = data15.length;
for(let i1=0; i1<len1; i1++){
const _errs48 = errors;
if(typeof data15[i1] !== "string"){
validate68.errors = [{instancePath:instancePath+"/files_changed/" + i1,schemaPath:"#/properties/files_changed/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid6 = _errs48 === errors;
if(!valid6){
break;
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/files_changed",schemaPath:"#/properties/files_changed/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs46 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.logs_path !== undefined){
const _errs50 = errors;
if(typeof data.logs_path !== "string"){
validate68.errors = [{instancePath:instancePath+"/logs_path",schemaPath:"#/properties/logs_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs50 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs52 = errors;
if(typeof data.success !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs52 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.summary !== undefined){
let data19 = data.summary;
const _errs54 = errors;
const _errs55 = errors;
let valid7 = false;
const _errs56 = errors;
if(typeof data19 !== "string"){
const err12 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs56 === errors;
valid7 = valid7 || _valid4;
const _errs58 = errors;
if(data19 !== null){
const err13 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs58 === errors;
valid7 = valid7 || _valid4;
if(!valid7){
const err14 = {instancePath:instancePath+"/summary",schemaPath:"#/properties/summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs55;
if(vErrors !== null){
if(_errs55){
vErrors.length = _errs55;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs54 === errors;
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
else {
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};
