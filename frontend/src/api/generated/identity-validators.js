// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateEntityChangePreview = validate53;
const schema20 = {"properties":{"command":{"$ref":"#/components/schemas/EntityChangeCommand"},"correction_history_may_block_revert":{"title":"Correction History May Block Revert","type":"boolean"},"entity":{"$ref":"#/components/schemas/IdentityEntity"},"evidence_event_ids":{"additionalProperties":{"items":{"type":"string"},"type":"array"},"title":"Evidence Event Ids","type":"object"},"fingerprint":{"title":"Fingerprint","type":"string"},"impact":{"$ref":"#/components/schemas/EntityChangeImpact"},"target":{"anyOf":[{"$ref":"#/components/schemas/IdentityEntity"},{"type":"null"}],"default":null}},"required":["command","entity","target","fingerprint","impact","correction_history_may_block_revert","evidence_event_ids"],"title":"EntityChangePreview","type":"object"};
const schema21 = {"additionalProperties":false,"properties":{"entity_id":{"maxLength":512,"minLength":1,"title":"Entity Id","type":"string"},"kind":{"enum":["type_correction","merge"],"title":"Kind","type":"string"},"new_type":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"New Type"},"review_id":{"anyOf":[{"maxLength":128,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Review Id"},"target_entity_id":{"anyOf":[{"maxLength":512,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Target Entity Id"}},"required":["kind","entity_id","target_entity_id","new_type","review_id"],"title":"EntityChangeCommand","type":"object"};
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
if((((((data.kind === undefined) && (missing0 = "kind")) || ((data.entity_id === undefined) && (missing0 = "entity_id"))) || ((data.target_entity_id === undefined) && (missing0 = "target_entity_id"))) || ((data.new_type === undefined) && (missing0 = "new_type"))) || ((data.review_id === undefined) && (missing0 = "review_id"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "entity_id") || (key0 === "kind")) || (key0 === "new_type")) || (key0 === "review_id")) || (key0 === "target_entity_id"))){
validate54.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.entity_id !== undefined){
let data0 = data.entity_id;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func1(data0) > 512){
validate54.errors = [{instancePath:instancePath+"/entity_id",schemaPath:"#/properties/entity_id/maxLength",keyword:"maxLength",params:{limit: 512},message:"must NOT have more than 512 characters"}];
return false;
}
else {
if(func1(data0) < 1){
validate54.errors = [{instancePath:instancePath+"/entity_id",schemaPath:"#/properties/entity_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/entity_id",schemaPath:"#/properties/entity_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data1 = data.kind;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate54.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data1 === "type_correction") || (data1 === "merge"))){
validate54.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema21.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.new_type !== undefined){
let data2 = data.new_type;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/new_type",schemaPath:"#/properties/new_type/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/new_type",schemaPath:"#/properties/new_type/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/new_type",schemaPath:"#/properties/new_type/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.review_id !== undefined){
let data3 = data.review_id;
const _errs12 = errors;
const _errs13 = errors;
let valid2 = false;
const _errs14 = errors;
if(errors === _errs14){
if(typeof data3 === "string"){
if(func1(data3) > 128){
const err3 = {instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/anyOf/0/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
else {
if(func1(data3) < 1){
const err4 = {instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/anyOf/0/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
}
}
else {
const err5 = {instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
}
var _valid1 = _errs14 === errors;
valid2 = valid2 || _valid1;
const _errs16 = errors;
if(data3 !== null){
const err6 = {instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs16 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
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
if(data.target_entity_id !== undefined){
let data4 = data.target_entity_id;
const _errs18 = errors;
const _errs19 = errors;
let valid3 = false;
const _errs20 = errors;
if(errors === _errs20){
if(typeof data4 === "string"){
if(func1(data4) > 512){
const err8 = {instancePath:instancePath+"/target_entity_id",schemaPath:"#/properties/target_entity_id/anyOf/0/maxLength",keyword:"maxLength",params:{limit: 512},message:"must NOT have more than 512 characters"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
else {
if(func1(data4) < 1){
const err9 = {instancePath:instancePath+"/target_entity_id",schemaPath:"#/properties/target_entity_id/anyOf/0/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
}
}
else {
const err10 = {instancePath:instancePath+"/target_entity_id",schemaPath:"#/properties/target_entity_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
}
var _valid2 = _errs20 === errors;
valid3 = valid3 || _valid2;
const _errs22 = errors;
if(data4 !== null){
const err11 = {instancePath:instancePath+"/target_entity_id",schemaPath:"#/properties/target_entity_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid2 = _errs22 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err12 = {instancePath:instancePath+"/target_entity_id",schemaPath:"#/properties/target_entity_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate54.errors = vErrors;
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

const schema22 = {"properties":{"canonical_name":{"title":"Canonical Name","type":"string"},"entity_id":{"title":"Entity Id","type":"string"},"entity_type":{"title":"Entity Type","type":"string"}},"required":["entity_id","canonical_name","entity_type"],"title":"IdentityEntity","type":"object"};

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
if((((data.entity_id === undefined) && (missing0 = "entity_id")) || ((data.canonical_name === undefined) && (missing0 = "canonical_name"))) || ((data.entity_type === undefined) && (missing0 = "entity_type"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.canonical_name !== undefined){
const _errs1 = errors;
if(typeof data.canonical_name !== "string"){
validate56.errors = [{instancePath:instancePath+"/canonical_name",schemaPath:"#/properties/canonical_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.entity_id !== undefined){
const _errs3 = errors;
if(typeof data.entity_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/entity_id",schemaPath:"#/properties/entity_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.entity_type !== undefined){
const _errs5 = errors;
if(typeof data.entity_type !== "string"){
validate56.errors = [{instancePath:instancePath+"/entity_type",schemaPath:"#/properties/entity_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"canonical_name":true,"entity_id":true,"entity_type":true},"dynamicProps":false,"dynamicItems":false};

const schema23 = {"properties":{"affected_subjects":{"title":"Affected Subjects","type":"integer"},"assertions":{"title":"Assertions","type":"integer"},"claims":{"title":"Claims","type":"integer"},"corrections":{"title":"Corrections","type":"integer"},"mentions":{"title":"Mentions","type":"integer"},"relationships":{"title":"Relationships","type":"integer"},"source_bindings":{"title":"Source Bindings","type":"integer"}},"required":["relationships","assertions","mentions","claims","corrections","source_bindings","affected_subjects"],"title":"EntityChangeImpact","type":"object"};

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
if((((((((data.relationships === undefined) && (missing0 = "relationships")) || ((data.assertions === undefined) && (missing0 = "assertions"))) || ((data.mentions === undefined) && (missing0 = "mentions"))) || ((data.claims === undefined) && (missing0 = "claims"))) || ((data.corrections === undefined) && (missing0 = "corrections"))) || ((data.source_bindings === undefined) && (missing0 = "source_bindings"))) || ((data.affected_subjects === undefined) && (missing0 = "affected_subjects"))){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.affected_subjects !== undefined){
let data0 = data.affected_subjects;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate58.errors = [{instancePath:instancePath+"/affected_subjects",schemaPath:"#/properties/affected_subjects/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.assertions !== undefined){
let data1 = data.assertions;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate58.errors = [{instancePath:instancePath+"/assertions",schemaPath:"#/properties/assertions/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.claims !== undefined){
let data2 = data.claims;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate58.errors = [{instancePath:instancePath+"/claims",schemaPath:"#/properties/claims/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.corrections !== undefined){
let data3 = data.corrections;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate58.errors = [{instancePath:instancePath+"/corrections",schemaPath:"#/properties/corrections/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.mentions !== undefined){
let data4 = data.mentions;
const _errs9 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate58.errors = [{instancePath:instancePath+"/mentions",schemaPath:"#/properties/mentions/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.relationships !== undefined){
let data5 = data.relationships;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate58.errors = [{instancePath:instancePath+"/relationships",schemaPath:"#/properties/relationships/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_bindings !== undefined){
let data6 = data.source_bindings;
const _errs13 = errors;
if(!((typeof data6 == "number") && (!(data6 % 1) && !isNaN(data6)))){
validate58.errors = [{instancePath:instancePath+"/source_bindings",schemaPath:"#/properties/source_bindings/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
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
}
else {
validate58.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate58.errors = vErrors;
return errors === 0;
}
validate58.evaluated = {"props":{"affected_subjects":true,"assertions":true,"claims":true,"corrections":true,"mentions":true,"relationships":true,"source_bindings":true},"dynamicProps":false,"dynamicItems":false};


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
if((((((((data.command === undefined) && (missing0 = "command")) || ((data.entity === undefined) && (missing0 = "entity"))) || ((data.target === undefined) && (missing0 = "target"))) || ((data.fingerprint === undefined) && (missing0 = "fingerprint"))) || ((data.impact === undefined) && (missing0 = "impact"))) || ((data.correction_history_may_block_revert === undefined) && (missing0 = "correction_history_may_block_revert"))) || ((data.evidence_event_ids === undefined) && (missing0 = "evidence_event_ids"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.command !== undefined){
const _errs1 = errors;
if(!(validate54(data.command, {instancePath:instancePath+"/command",parentData:data,parentDataProperty:"command",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.correction_history_may_block_revert !== undefined){
const _errs2 = errors;
if(typeof data.correction_history_may_block_revert !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/correction_history_may_block_revert",schemaPath:"#/properties/correction_history_may_block_revert/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.entity !== undefined){
const _errs4 = errors;
if(!(validate56(data.entity, {instancePath:instancePath+"/entity",parentData:data,parentDataProperty:"entity",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.evidence_event_ids !== undefined){
let data3 = data.evidence_event_ids;
const _errs5 = errors;
if(errors === _errs5){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key0 in data3){
let data4 = data3[key0];
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data4)){
var valid2 = true;
const len0 = data4.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(typeof data4[i0] !== "string"){
validate53.errors = [{instancePath:instancePath+"/evidence_event_ids/" + key0.replace(/~/g, "~0").replace(/\//g, "~1")+"/" + i0,schemaPath:"#/properties/evidence_event_ids/additionalProperties/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/evidence_event_ids/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/evidence_event_ids/additionalProperties/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid1 = _errs8 === errors;
if(!valid1){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/evidence_event_ids",schemaPath:"#/properties/evidence_event_ids/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fingerprint !== undefined){
const _errs12 = errors;
if(typeof data.fingerprint !== "string"){
validate53.errors = [{instancePath:instancePath+"/fingerprint",schemaPath:"#/properties/fingerprint/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.impact !== undefined){
const _errs14 = errors;
if(!(validate58(data.impact, {instancePath:instancePath+"/impact",parentData:data,parentDataProperty:"impact",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.target !== undefined){
let data8 = data.target;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(!(validate56(data8, {instancePath:instancePath+"/target",parentData:data,parentDataProperty:"target",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var _valid0 = _errs17 === errors;
valid3 = valid3 || _valid0;
if(_valid0){
var props0 = {};
props0.canonical_name = true;
props0.entity_id = true;
props0.entity_type = true;
}
const _errs18 = errors;
if(data8 !== null){
const err0 = {instancePath:instancePath+"/target",schemaPath:"#/properties/target/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs18 === errors;
valid3 = valid3 || _valid0;
if(!valid3){
const err1 = {instancePath:instancePath+"/target",schemaPath:"#/properties/target/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate53.errors = vErrors;
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
validate53.evaluated = {"props":{"command":true,"correction_history_may_block_revert":true,"entity":true,"evidence_event_ids":true,"fingerprint":true,"impact":true,"target":true},"dynamicProps":false,"dynamicItems":false};

export const validateEntityChangeResult = validate61;
const schema24 = {"properties":{"current_type":{"title":"Current Type","type":"string"},"derivation_state":{"const":"pending","default":"pending","title":"Derivation State","type":"string"},"entity_id":{"title":"Entity Id","type":"string"},"impact":{"$ref":"#/components/schemas/EntityChangeImpact"},"kind":{"enum":["type_correction","merge"],"title":"Kind","type":"string"},"operation_id":{"title":"Operation Id","type":"string"}},"required":["operation_id","kind","entity_id","current_type","impact","derivation_state"],"title":"EntityChangeResult","type":"object"};

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
if(((((((data.operation_id === undefined) && (missing0 = "operation_id")) || ((data.kind === undefined) && (missing0 = "kind"))) || ((data.entity_id === undefined) && (missing0 = "entity_id"))) || ((data.current_type === undefined) && (missing0 = "current_type"))) || ((data.impact === undefined) && (missing0 = "impact"))) || ((data.derivation_state === undefined) && (missing0 = "derivation_state"))){
validate61.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.current_type !== undefined){
const _errs1 = errors;
if(typeof data.current_type !== "string"){
validate61.errors = [{instancePath:instancePath+"/current_type",schemaPath:"#/properties/current_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.derivation_state !== undefined){
let data1 = data.derivation_state;
const _errs3 = errors;
if(typeof data1 !== "string"){
validate61.errors = [{instancePath:instancePath+"/derivation_state",schemaPath:"#/properties/derivation_state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("pending" !== data1){
validate61.errors = [{instancePath:instancePath+"/derivation_state",schemaPath:"#/properties/derivation_state/const",keyword:"const",params:{allowedValue: "pending"},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.entity_id !== undefined){
const _errs5 = errors;
if(typeof data.entity_id !== "string"){
validate61.errors = [{instancePath:instancePath+"/entity_id",schemaPath:"#/properties/entity_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.impact !== undefined){
const _errs7 = errors;
if(!(validate58(data.impact, {instancePath:instancePath+"/impact",parentData:data,parentDataProperty:"impact",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data4 = data.kind;
const _errs8 = errors;
if(typeof data4 !== "string"){
validate61.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data4 === "type_correction") || (data4 === "merge"))){
validate61.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema24.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.operation_id !== undefined){
const _errs10 = errors;
if(typeof data.operation_id !== "string"){
validate61.errors = [{instancePath:instancePath+"/operation_id",schemaPath:"#/properties/operation_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate61.evaluated = {"props":{"current_type":true,"derivation_state":true,"entity_id":true,"impact":true,"kind":true,"operation_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateEntityTypeReviewList = validate63;
const schema25 = {"properties":{"items":{"items":{"$ref":"#/components/schemas/EntityTypeReview"},"title":"Items","type":"array"},"total":{"title":"Total","type":"integer"}},"required":["items","total"],"title":"EntityTypeReviewList","type":"object"};
const schema26 = {"properties":{"entity":{"$ref":"#/components/schemas/IdentityEntity"},"evidence_event_ids":{"items":{"type":"string"},"title":"Evidence Event Ids","type":"array"},"proposed_type":{"title":"Proposed Type","type":"string"},"review_id":{"title":"Review Id","type":"string"},"version":{"title":"Version","type":"integer"}},"required":["review_id","entity","proposed_type","evidence_event_ids","version"],"title":"EntityTypeReview","type":"object"};

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
if((((((data.review_id === undefined) && (missing0 = "review_id")) || ((data.entity === undefined) && (missing0 = "entity"))) || ((data.proposed_type === undefined) && (missing0 = "proposed_type"))) || ((data.evidence_event_ids === undefined) && (missing0 = "evidence_event_ids"))) || ((data.version === undefined) && (missing0 = "version"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.entity !== undefined){
const _errs1 = errors;
if(!(validate56(data.entity, {instancePath:instancePath+"/entity",parentData:data,parentDataProperty:"entity",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.evidence_event_ids !== undefined){
let data1 = data.evidence_event_ids;
const _errs2 = errors;
if(errors === _errs2){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs4 = errors;
if(typeof data1[i0] !== "string"){
validate64.errors = [{instancePath:instancePath+"/evidence_event_ids/" + i0,schemaPath:"#/properties/evidence_event_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs4 === errors;
if(!valid1){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/evidence_event_ids",schemaPath:"#/properties/evidence_event_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.proposed_type !== undefined){
const _errs6 = errors;
if(typeof data.proposed_type !== "string"){
validate64.errors = [{instancePath:instancePath+"/proposed_type",schemaPath:"#/properties/proposed_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.review_id !== undefined){
const _errs8 = errors;
if(typeof data.review_id !== "string"){
validate64.errors = [{instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
let data5 = data.version;
const _errs10 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate64.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
}
else {
validate64.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate64.errors = vErrors;
return errors === 0;
}
validate64.evaluated = {"props":{"entity":true,"evidence_event_ids":true,"proposed_type":true,"review_id":true,"version":true},"dynamicProps":false,"dynamicItems":false};


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
if(((data.items === undefined) && (missing0 = "items")) || ((data.total === undefined) && (missing0 = "total"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.items !== undefined){
let data0 = data.items;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate64(data0[i0], {instancePath:instancePath+"/items/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate63.errors = [{instancePath:instancePath+"/items",schemaPath:"#/properties/items/type",keyword:"type",params:{type: "array"},message:"must be array"}];
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
validate63.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":{"items":true,"total":true},"dynamicProps":false,"dynamicItems":false};

export const validateEntityReviewRejectResult = validate67;
const schema27 = {"properties":{"review_id":{"title":"Review Id","type":"string"},"status":{"const":"rejected","default":"rejected","title":"Status","type":"string"}},"required":["review_id","status"],"title":"EntityReviewRejectResult","type":"object"};

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
if(((data.review_id === undefined) && (missing0 = "review_id")) || ((data.status === undefined) && (missing0 = "status"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.review_id !== undefined){
const _errs1 = errors;
if(typeof data.review_id !== "string"){
validate67.errors = [{instancePath:instancePath+"/review_id",schemaPath:"#/properties/review_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data1 = data.status;
const _errs3 = errors;
if(typeof data1 !== "string"){
validate67.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("rejected" !== data1){
validate67.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/const",keyword:"const",params:{allowedValue: "rejected"},message:"must be equal to constant"}];
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
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":{"review_id":true,"status":true},"dynamicProps":false,"dynamicItems":false};

export const validateEntityIdentityAudit = validate68;
const schema28 = {"properties":{"groups":{"items":{"$ref":"#/components/schemas/EntityIdentityAuditGroup"},"title":"Groups","type":"array"},"total":{"title":"Total","type":"integer"}},"required":["groups","total"],"title":"EntityIdentityAudit","type":"object"};
const schema29 = {"properties":{"entities":{"items":{"$ref":"#/components/schemas/IdentityEntity"},"title":"Entities","type":"array"},"name":{"title":"Name","type":"string"}},"required":["name","entities"],"title":"EntityIdentityAuditGroup","type":"object"};

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
if(((data.name === undefined) && (missing0 = "name")) || ((data.entities === undefined) && (missing0 = "entities"))){
validate69.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.entities !== undefined){
let data0 = data.entities;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate56(data0[i0], {instancePath:instancePath+"/entities/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/entities",schemaPath:"#/properties/entities/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs4 = errors;
if(typeof data.name !== "string"){
validate69.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate69.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate69.errors = vErrors;
return errors === 0;
}
validate69.evaluated = {"props":{"entities":true,"name":true},"dynamicProps":false,"dynamicItems":false};


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
if(((data.groups === undefined) && (missing0 = "groups")) || ((data.total === undefined) && (missing0 = "total"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.groups !== undefined){
let data0 = data.groups;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate69(data0[i0], {instancePath:instancePath+"/groups/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate69.errors : vErrors.concat(validate69.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate68.errors = [{instancePath:instancePath+"/groups",schemaPath:"#/properties/groups/type",keyword:"type",params:{type: "array"},message:"must be array"}];
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
validate68.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":{"groups":true,"total":true},"dynamicProps":false,"dynamicItems":false};
